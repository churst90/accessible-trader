import ccxt.async_support as ccxt
import logging
import asyncio
from collections import defaultdict
import pandas as pd
from contextlib import asynccontextmanager
from managers.config_manager import config_manager

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class CryptoDataFetcher:
    TIMEFRAME_UNITS = {'m': 60 * 1000, 'h': 60 * 60 * 1000, 'd': 24 * 60 * 60 * 1000}
    DEFAULT_LIMIT = 1000

    def __init__(self, event_bus):
        self.event_bus = event_bus
        # Subscribe to the fetch_data event
        self.event_bus.subscribe("fetch_data", self.fetch_data)
        self.use_cache = config_manager.get('data', {}).get('use_cache', True)

    async def fetch_data(self, exchange_id, symbol, timeframe):
        print(f"Received fetch_data event: exchange_id={exchange_id}, symbol={symbol}, timeframe={timeframe}")

        async with self.exchange_session(exchange_id) as exchange:
            ohlcv_data = await self.fetch_ohlcv_in_batches(exchange, symbol, timeframe)

        if ohlcv_data is None or ohlcv_data.empty:
            print("No data fetched, publishing empty DataFrame.")
            await self.event_bus.publish("data_fetched", pd.DataFrame())  # Always pass only the DataFrame
        else:
            df = self.ohlcv_to_dataframe(ohlcv_data)
            print("Data fetched successfully, publishing data_fetched event.")
            await self.event_bus.publish("data_fetched", df)  # Always pass only the DataFrame

    @asynccontextmanager
    async def exchange_session(self, exchange_id):
        """Context manager to handle the exchange session lifecycle."""
        exchange = getattr(ccxt, exchange_id)({'enableRateLimit': True})
        try:
            await exchange.load_markets()
            yield exchange
        finally:
            await exchange.close()

    @staticmethod
    def get_exchanges():
        """Return a list of supported exchanges."""
        return ccxt.exchanges

    def ohlcv_to_dataframe(self, ohlcv_data):
        """Convert OHLCV data to a pandas DataFrame."""
        df = pd.DataFrame(ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df

    async def fetch_with_retries(self, method, *args, max_retries=5, delay=1, **kwargs):
        """Fetch data with retry logic for network errors."""
        retries = 0
        while retries < max_retries:
            try:
                return await method(*args, **kwargs)
            except ccxt.NetworkError as e:
                print(f"Network error: {e}. Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
                retries += 1
                delay *= 2
            except ccxt.ExchangeError as e:
                print(f"Exchange error: {e}. Aborting...")
                await self.event_bus.publish("data_fetch_error", e)
                break
            except Exception as e:
                print(f"Unexpected error: {e}. Aborting...")
                await self.event_bus.publish("data_fetch_error", e)
                break
        return None

    async def fetch_ohlcv_in_batches(self, exchange, symbol, timeframe, since=None, until=None, limit=DEFAULT_LIMIT):
        """Fetch OHLCV data in batches, supporting caching."""
        print("fetch OHLCV in batches executed")
        if not self.is_timeframe_supported(exchange, timeframe):
            print("Timeframe not supported. Attempting to aggregate from smaller timeframe.")
            base_timeframe = '1m'
            return await self._aggregate_data_fallback(exchange, symbol, base_timeframe, timeframe, since, until, limit)

        # Fetch fresh data from exchange for the specified symbol and timeframe
        data = await self.fetch_with_retries(exchange.fetch_ohlcv, symbol, timeframe, since=since, limit=limit)
        
        if data is None:
            return pd.DataFrame()  # Return empty DataFrame on failure

        df = self.ohlcv_to_dataframe(data)

        # Publish the event with the fetched data
        await self.event_bus.publish("data_fetched", df)
        return df

    def is_timeframe_supported(self, exchange, timeframe):
        """Check if the requested timeframe is supported by the exchange."""
        return timeframe in exchange.timeframes

    async def _aggregate_data_fallback(self, exchange, symbol, base_timeframe, target_timeframe, since, until, limit):
        """Aggregate data from a smaller timeframe if the requested one is unsupported."""
        base_data = await self.fetch_with_retries(exchange.fetch_ohlcv, symbol, base_timeframe, since=since, limit=limit)
        
        if base_data is None:
            return pd.DataFrame()  # Return empty DataFrame on failure

        aggregated_data = self.aggregate_ohlcv(base_data, self.convert_to_milliseconds(target_timeframe))
        df = self.ohlcv_to_dataframe(aggregated_data)
        await self.event_bus.publish("data_fetched", df)
        return df

    def aggregate_ohlcv(self, ohlcv, target_timeframe_ms):
        """Aggregate OHLCV data to a larger timeframe."""
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

    def convert_to_milliseconds(self, timeframe):
        """Convert a timeframe string (e.g., '1m', '1h') to milliseconds."""
        try:
            unit = timeframe[-1]
            amount = int(timeframe[:-1])
            return amount * CryptoDataFetcher.TIMEFRAME_UNITS[unit]
        except ValueError as e:
            print(f"Invalid timeframe: {timeframe}. Error: {e}")
            raise
