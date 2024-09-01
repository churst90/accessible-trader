import ccxt.async_support as ccxt
import logging
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
import diskcache as dc
import os
import pandas as pd
import pickle
from contextlib import asynccontextmanager

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize a persistent cache using diskcache with a TTL of 5 minutes
cache_dir = os.path.join(os.getcwd(), 'ohlcv_cache')
cache = dc.Cache(cache_dir)

class CryptoDataFetcher:
    TIMEFRAME_UNITS = {'m': 60 * 1000, 'h': 60 * 60 * 1000, 'd': 24 * 60 * 60 * 1000}
    DEFAULT_LIMIT = 1000

    def __init__(self, exchange_id):
        assert exchange_id in ccxt.exchanges, f"{exchange_id} is not a supported exchange"
        self.exchange = getattr(ccxt, exchange_id)({'enableRateLimit': True})
        self.loop = asyncio.get_event_loop()

    @asynccontextmanager
    async def exchange_session(self):
        try:
            await self.exchange.load_markets()
            yield self.exchange
        finally:
            await self.exchange.close()

    @staticmethod
    def get_exchanges():
        return ccxt.exchanges

    def get_symbols(self):
        return self.exchange.symbols if hasattr(self.exchange, 'symbols') else []

    @staticmethod
    def convert_to_milliseconds(timeframe):
        try:
            unit = timeframe[-1]
            amount = int(timeframe[:-1])
            return amount * CryptoDataFetcher.TIMEFRAME_UNITS[unit]
        except ValueError as e:
            logging.error(f"Invalid timeframe: {timeframe}. Error: {e}")
            raise

    def is_timeframe_supported(self, timeframe):
        return timeframe in self.exchange.timeframes

    def check_market_availability(self, symbol):
        return symbol in self.get_symbols()

    def ohlcv_to_dataframe(self, ohlcv_data):
        df = pd.DataFrame(ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df

    async def fetch_with_retries(self, method, *args, max_retries=5, delay=1, **kwargs):
        retries = 0
        while retries < max_retries:
            try:
                return await method(*args, **kwargs)
            except ccxt.NetworkError as e:
                logging.warning(f"Network error: {e}. Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
                retries += 1
                delay *= 2
            except ccxt.ExchangeError as e:
                logging.error(f"Exchange error: {e}. Aborting...")
                break
            except Exception as e:
                logging.error(f"Unexpected error: {e}. Aborting...")
                break
        return None

    async def fetch_ohlcv_in_batches(self, symbol, timeframe, since=None, until=None, limit=DEFAULT_LIMIT, use_cache=True):
        if not self.is_timeframe_supported(timeframe):
            logging.error("Timeframe not supported. Attempting to aggregate from smaller timeframe.")
            base_timeframe = '1m'
            return await self._aggregate_data_fallback(symbol, base_timeframe, timeframe, since, until, limit)

        cache_key = (self.exchange.id, symbol, timeframe, since, until)
        if use_cache and cache_key in cache:
            logging.info(f"Fetching data from cache for {symbol} on {self.exchange.id}")
            return pickle.loads(cache.get(cache_key))

        logging.info(f"Fetching fresh data from exchange for {symbol} on {self.exchange.id}")
        
        async with self.exchange_session() as exchange:
            data = await self.fetch_with_retries(exchange.fetch_ohlcv, symbol, timeframe, since=since, limit=limit)
        
        df = self.ohlcv_to_dataframe(data)

        # Update the cache with fresh data
        cache.set(cache_key, pickle.dumps(df))  # Cache the DataFrame
        return df

    async def _fetch_data_directly(self, symbol, timeframe, since, until, limit):
        all_data = []
        last_timestamp = since
        while True:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, since=last_timestamp, limit=limit)
            if not ohlcv:
                break

            all_data.extend(ohlcv)
            last_timestamp = ohlcv[-1][0]

            if until and last_timestamp >= until:
                break

            await asyncio.sleep(self.exchange.rateLimit / 1000)
        return all_data

    async def _aggregate_data_fallback(self, symbol, base_timeframe, target_timeframe, since, until, limit):
        async with self.exchange_session() as exchange:
            base_data = await self.fetch_with_retries(exchange.fetch_ohlcv, symbol, base_timeframe, since=since, limit=limit)
        
        aggregated_data = self.aggregate_ohlcv(base_data, self.convert_to_milliseconds(target_timeframe))
        return self.ohlcv_to_dataframe(aggregated_data)

    def aggregate_ohlcv(self, ohlcv, target_timeframe_ms):
        aggregated_data = []
        bucket = defaultdict(lambda: [float('inf'), float('-inf'), None, None, 0])
        for entry in ohlcv:
            timestamp, open, high, low, close, volume = entry
            bucket_key = (timestamp // target_timeframe_ms) * target_timeframe_ms
            if bucket[bucket_key][2] is None:
                bucket[bucket_key][0] = open
            bucket[bucket_key][1] = max(bucket[bucket_key][1], high)
            bucket[bucket_key][2] = close
            bucket[bucket_key][3] = min(bucket[bucket_key][3], low) if bucket[bucket_key][3] is not None else low
            bucket[bucket_key][4] += volume

        for key, (open, high, close, low, volume) in bucket.items():
            aggregated_data.append([key, open, high, low, close, volume])

        return sorted(aggregated_data, key=lambda x: x[0])

    async def fetch_historical_data(self, symbol, timeframe, since, until, limit=DEFAULT_LIMIT):
        historical_data = []
        current_end_time = until

        async with self.exchange_session() as exchange:
            while current_end_time > since:
                ohlcv = await self.fetch_with_retries(
                    exchange.fetch_ohlcv, symbol, timeframe, since, limit, params={'endTime': current_end_time})
                if not ohlcv:
                    break

                historical_data = ohlcv + historical_data
                current_end_time = ohlcv[0][0] - 1

                await asyncio.sleep(exchange.rateLimit / 1000)

        return self.ohlcv_to_dataframe(historical_data)

    async def fetch_data_live(self, symbol, timeframe, since, limit=DEFAULT_LIMIT):
        latest_data = []
        current_time = self.convert_datetime_to_milliseconds(datetime.utcnow())

        async with self.exchange_session() as exchange:
            while since < current_time:
                ohlcv = await self.fetch_with_retries(exchange.fetch_ohlcv, symbol, timeframe, since, limit)
                if not ohlcv:
                    break

                latest_data.extend(ohlcv)
                since = ohlcv[-1][0] + 1
                await asyncio.sleep(exchange.rateLimit / 1000)
                current_time = self.convert_datetime_to_milliseconds(datetime.utcnow())

        return self.ohlcv_to_dataframe(latest_data)

    def convert_datetime_to_milliseconds(self, dt):
        return int(dt.timestamp() * 1000)

    async def fetch_multiple_symbols_with_limit(self, symbols, timeframe, since, until, limit, max_concurrent_requests):
        semaphore = asyncio.Semaphore(max_concurrent_requests)
        tasks = [self.fetch_with_semaphore(semaphore, symbol, timeframe, since, until, limit) for symbol in symbols]
        return await asyncio.gather(*tasks)

    async def fetch_with_semaphore(self, semaphore, symbol, timeframe, since, until, limit):
        async with semaphore:
            return await self.fetch_ohlcv_in_batches(symbol, timeframe, since, until, limit)

if __name__ == '__main__':
    fetcher = CryptoDataFetcher('binance')
    loop = asyncio.get_event_loop()
    loop.run_until_complete(fetcher.load_markets())
    since_timestamp = int((datetime.utcnow() - timedelta(days=1)).timestamp() * 1000)
    until_timestamp = int(datetime.utcnow().timestamp() * 1000)

    loop.run_until_complete(fetcher.fetch_multiple_symbols_with_limit(['BTC/USDT', 'ETH/USDT'], '1m', since_timestamp, until_timestamp, limit=1000, max_concurrent_requests=5))
