import asyncio
import ccxt.async_support as ccxt
from ccxt.base.errors import NetworkError, ExchangeError, RateLimitExceeded
import logging

logger = logging.getLogger("CryptoPlugin")

class CryptoPlugin:
    def __init__(self):
        self._instances = {}
        self._supported_exchanges = ccxt.exchanges

    async def get_exchanges(self):
        """
        Retrieve the list of supported exchanges.
        Although this doesn't perform I/O, we keep it async for consistency.
        """
        logger.info("Fetching list of supported cryptocurrency exchanges.")
        # No I/O, just return the static list
        return self._supported_exchanges

    def _get_exchange_instance(self, exchange_name):
        if exchange_name not in self._supported_exchanges:
            logger.error(f"Exchange '{exchange_name}' is not supported.")
            raise ValueError(f"Exchange '{exchange_name}' is not supported.")

        if exchange_name not in self._instances:
            try:
                self._instances[exchange_name] = getattr(ccxt, exchange_name)({"enableRateLimit": True})
                logger.info(f"Initialized exchange instance for '{exchange_name}'.")
            except AttributeError as e:
                logger.error(f"Failed to initialize exchange '{exchange_name}': {e}")
                raise ValueError(f"Failed to initialize exchange '{exchange_name}': {e}")

        return self._instances[exchange_name]

    async def fetch_with_retries(self, func, *args, retries=3, delay=1, **kwargs):
        for attempt in range(retries):
            try:
                return await func(*args, **kwargs)
            except (NetworkError, ExchangeError, RateLimitExceeded) as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying...")
                if attempt == retries - 1:
                    logger.error(f"Max retries reached. Operation failed: {e}")
                    raise
                await asyncio.sleep(delay)

    async def get_symbols(self, exchange_name):
        exchange_instance = self._get_exchange_instance(exchange_name)
        try:
            logger.info(f"Fetching trading symbols for exchange '{exchange_name}'.")
            markets = await self.fetch_with_retries(exchange_instance.load_markets)
            return list(markets.keys())
        except Exception as e:
            logger.error(f"Failed to fetch symbols for exchange '{exchange_name}': {e}")
            raise ValueError(f"Failed to fetch symbols for exchange '{exchange_name}': {e}")
        finally:
            await self._close_exchange_instance(exchange_name)

    async def fetch_ohlcv(self, exchange_name, symbol, timeframe="1h", since=None, limit=None):
        exchange_instance = self._get_exchange_instance(exchange_name)
        try:
            logger.info(f"Fetching OHLCV data for symbol '{symbol}' on exchange '{exchange_name}' with timeframe '{timeframe}'.")
            data = await self.fetch_with_retries(
                exchange_instance.fetch_ohlcv, symbol, timeframe, since, limit
            )
            logger.info(f"Fetched {len(data)} OHLCV records for '{symbol}' on '{exchange_name}'.")
            return [
                {
                    "timestamp": entry[0],
                    "open": entry[1],
                    "high": entry[2],
                    "low": entry[3],
                    "close": entry[4],
                    "volume": entry[5],
                }
                for entry in data
            ]
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV data for '{symbol}' on '{exchange_name}': {e}")
            raise ValueError(f"Failed to fetch OHLCV data for '{symbol}' on '{exchange_name}': {e}")
        finally:
            await self._close_exchange_instance(exchange_name)

    async def subscribe_to_ticker(self, symbols, callback):
        logger.info(f"Starting simulated ticker subscription for symbols: {symbols}")
        try:
            while True:
                for symbol in symbols:
                    simulated_data = {"symbol": symbol, "price": 100.0}
                    await callback(simulated_data)
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("Ticker subscription task canceled.")
        except Exception as e:
            logger.error(f"Error during ticker subscription: {e}")
            raise

    async def _close_exchange_instance(self, exchange_name):
        if exchange_name in self._instances:
            try:
                await self._instances[exchange_name].close()
                logger.info(f"Closed exchange instance for '{exchange_name}'.")
                del self._instances[exchange_name]
            except Exception as e:
                logger.error(f"Error closing exchange instance for '{exchange_name}': {e}")

    async def close_all(self):
        logger.info("Closing all exchange instances.")
        for exchange_name in list(self._instances.keys()):
            await self._close_exchange_instance(exchange_name)
