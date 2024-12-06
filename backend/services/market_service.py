import logging
import pandas as pd
from quart import current_app
from plugins import load_market_plugin
from utils.db_utils import fetch_ohlcv_from_db, insert_ohlcv_to_db

logger = logging.getLogger("MarketService")

class MarketService:
    def __init__(self, market):
        self.market = market
        self.plugin = load_market_plugin(market)

    async def get_exchanges(self):
        try:
            # Now async
            return await self.plugin.get_exchanges()
        except Exception as e:
            logger.error(f"Error retrieving exchanges for market '{self.market}': {e}")
            raise ValueError(f"Failed to retrieve exchanges: {e}")

    async def get_symbols(self, exchange):
        try:
            return await self.plugin.get_symbols(exchange)
        except Exception as e:
            logger.error(f"Error retrieving symbols for exchange '{exchange}' in market '{self.market}': {e}")
            raise ValueError(f"Failed to retrieve symbols: {e}")

    async def fetch_ohlcv(self, exchange, symbol, timeframe="1h", since=None, limit=None):
        cache = current_app.config.get("CACHE")
        cache_key = f"{self.market}:{exchange}:{symbol}:{timeframe}:{since}:{limit}"

        try:
            if cache:
                cached_data = await cache.get(cache_key)
                if cached_data:
                    logger.info(f"Cache hit for key: {cache_key}")
                    return cached_data

            db_data = await fetch_ohlcv_from_db(self.market, exchange, symbol, timeframe, since, limit)
            if db_data:
                logger.info(
                    f"Database hit for market='{self.market}', exchange='{exchange}', symbol='{symbol}', timeframe='{timeframe}'"
                )
                if cache:
                    await cache.set(cache_key, db_data, expire=300)
                return db_data

            logger.info(
                f"No cache or database data found. Fetching OHLCV data from API for market='{self.market}', exchange='{exchange}', symbol='{symbol}'."
            )
            raw_data = await self.plugin.fetch_ohlcv(exchange, symbol, timeframe, since, limit)

            aggregated_data = self._resample_ohlcv(raw_data, timeframe)

            await insert_ohlcv_to_db(self.market, exchange, symbol, timeframe, aggregated_data)
            if cache:
                await cache.set(cache_key, aggregated_data, expire=300)
            return aggregated_data
        except Exception as e:
            logger.error(
                f"Error fetching OHLCV data for market='{self.market}', exchange='{exchange}', symbol='{symbol}', timeframe='{timeframe}': {e}"
            )
            raise ValueError(f"Failed to fetch OHLCV data: {e}")

    def _resample_ohlcv(self, raw_data, target_timeframe):
        if not isinstance(raw_data, pd.DataFrame):
            raw_data = pd.DataFrame(
                raw_data, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
        raw_data["timestamp"] = pd.to_datetime(raw_data["timestamp"], unit="ms")

        timeframe_mapping = {
            '1m': '1T',
            '3m': '3T',
            '5m': '5T',
            '10m': '10T',
            '15m': '15T',
            '30m': '30T',
            '1h': '1H',
            '2h': '2H',
            '4h': '4H',
            '1d': '1D',
        }

        if target_timeframe not in timeframe_mapping:
            raise ValueError(f"Unsupported timeframe: {target_timeframe}")

        rule = timeframe_mapping[target_timeframe]
        resampled = raw_data.resample(rule, on="timestamp").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna()

        return [
            {
                "timestamp": int(idx.timestamp() * 1000),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"]
            }
            for idx, row in resampled.iterrows()
        ]

    def format_for_highcharts(self, ohlcv_data):
        try:
            ohlc = [
                [entry["timestamp"], entry["open"], entry["high"], entry["low"], entry["close"]]
                for entry in ohlcv_data
            ]
            volume = [
                [entry["timestamp"], entry["volume"]]
                for entry in ohlcv_data
            ]
            return {"ohlc": ohlc, "volume": volume}
        except KeyError as e:
            logger.error(f"Missing key in OHLCV data during formatting: {e}")
            raise ValueError("Invalid OHLCV data format.")
