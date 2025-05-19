# services/data_sources/plugin_source.py

import logging
from typing import Dict, List, Optional, Any

from quart import current_app
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from plugins.base import MarketPlugin, PluginError
from utils.db_utils import insert_ohlcv_to_db
from utils.timeframes import UNIT_MS

from .base import DataSource

logger = logging.getLogger("PluginSource")


class PluginSource(DataSource):
    """
    DataSource for fetching OHLCV bars from external plugins.

    Fetches bars using the plugin's native timeframe support when available, falling back to
    1-minute bars and resampling. Stores fetched bars in the database and cache.

    Attributes:
        market (str): The market identifier (e.g., "crypto", "stocks").
        provider (str): The provider identifier (e.g., "binance", "alpaca").
        symbol (str): The trading pair symbol (e.g., "BTC/USD").
        plugin (MarketPlugin): The plugin instance for data fetching.
        cache (Optional[Cache]): Cache manager for storing bars.
        resampler (Resampler): Resampler for converting 1m bars to higher timeframes.
        chunk_size (int): Maximum number of bars to fetch per plugin request.
    """

    def __init__(
        self,
        market: str,
        provider: str,
        symbol: str,
        plugin: MarketPlugin,
        cache: Optional["Cache"],  # String type hint to avoid circular import
        resampler: "Resampler",
    ):
        """
        Initialize the PluginSource.

        Args:
            market (str): The market identifier.
            provider (str): The provider identifier.
            symbol (str): The trading pair symbol.
            plugin (MarketPlugin): The plugin instance.
            cache (Optional[Cache]): Cache manager instance (e.g., RedisCache).
            resampler (Resampler): Resampler instance.

        Raises:
            ValueError: If market, provider, or symbol are invalid.
        """
        if not market or not provider:
            raise ValueError("market and provider  must be non-empty strings")
        self.market = market
        self.provider = provider
        self.symbol = symbol
        self.plugin = plugin
        self.cache = cache
        self.resampler = resampler
        self.chunk_size = int(current_app.config.get("DEFAULT_PLUGIN_CHUNK_SIZE", 500))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(PluginError),
        after=lambda retry_state: logger.warning(
            f"Plugin retry attempt {retry_state.attempt_number} failed"
        ),
    )
    async def fetch_ohlcv(
        self,
        timeframe: str,
        since: Optional[int],
        before: Optional[int],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars from the plugin, preferring native timeframe if supported.

        Args:
            timeframe (str): The timeframe string (e.g., "1m", "5m").
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            before (Optional[int]): End timestamp in milliseconds (exclusive).
            limit (int): Maximum number of bars to return.

        Returns:
            List[Dict[str, Any]]: List of OHLCV bars, each with keys:
                - timestamp (int): Milliseconds since epoch.
                - open (float): Opening price.
                - high (float): Highest price.
                - low (float): Lowest price.
                - close (float): Closing price.
                - volume (float): Trading volume.

        Raises:
            PluginError: If the plugin fetch fails (retried automatically).
        """
        fetch_since = since
        if fetch_since is None:
            fetch_since = (before or int(time.time() * 1000)) - (self.chunk_size * UNIT_MS["m"])

        try:
            supported = await self.plugin.supported_timeframes(self.provider, self.symbol)
            fetch_timeframe = timeframe if timeframe in supported else "1m"
            bars = await self.plugin.fetch_historical_ohlcv(
                provider=self.provider,
                symbol=self.symbol,
                timeframe=fetch_timeframe,
                since=fetch_since,
                limit=min(limit, self.chunk_size),
            )
            if not bars:
                logger.debug(f"Plugin returned no data for {fetch_timeframe}")
                return []

            # Store fetched bars
            await insert_ohlcv_to_db(self.market, self.provider, self.symbol, fetch_timeframe, bars)
            if self.cache:
                try:
                    await self.cache.store_1m_bars(self.market, self.provider, self.symbol, bars)
                    logger.debug(f"Stored {len(bars)} bars in cache")
                except Exception as e:
                    logger.warning(f"Failed to store bars in cache: {e}", exc_info=True)

            # Resample if needed
            if fetch_timeframe != timeframe:
                bars = self.resampler.resample(bars, timeframe)

            logger.debug(f"Fetched {len(bars)} bars from plugin for {fetch_timeframe}")
            return bars
        except PluginError as e:
            logger.error(f"Plugin fetch failed: {e}", exc_info=True)
            raise