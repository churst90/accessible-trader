# services/data_source/cache_source.py

import logging
from typing import Dict, List, Optional, Any

from quart import current_app
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from utils.db_utils import fetch_ohlcv_from_db
from utils.timeframes import UNIT_MS, _parse_timeframe_str

from .base import DataSource
from ..cache_manager import Cache
from ..resampler import Resampler

logger = logging.getLogger("CacheSource")


class CacheSource(DataSource):
    """
    DataSource for fetching OHLCV bars from Redis cache with database fallback.

    Attempts to fetch resampled bars for non-1m timeframes from cache. For 1m or cache misses,
    fetches 1m bars from cache or database, resampling if needed. Caches resampled results.

    Attributes:
        market (str): The market identifier (e.g., "crypto", "stocks").
        provider (str): The provider identifier (e.g., "binance", "alpaca").
        symbol (str): The trading pair symbol (e.g., "BTC/USD").
        cache (Optional[CacheManager]): Cache manager for Redis operations.
        resampler (Resampler): Resampler for converting 1m bars to higher timeframes.
        resampled_ttl (int): TTL for cached resampled bars (seconds).
    """

    def __init__(
        self,
        market: str,
        provider: str,
        symbol: str,
        cache: Optional[Cache],
        resampler: Resampler,
    ):
        """
        Initialize the CacheSource.

        Args:
            market (str): The market identifier.
            provider (str): The provider identifier.
            symbol (str): The trading pair symbol.
            cache (Optional[CacheManager]): Cache manager instance.
            resampler (Resampler): Resampler instance.

        Raises:
            ValueError: If market, provider, or symbol are invalid.
        """
        if not market or not provider:
            raise ValueError("market and provider must be non-empty strings")
        self.market = market
        self.provider = provider
        self.symbol = symbol
        self.cache = cache
        self.resampler = resampler
        self.resampled_ttl = int(current_app.config.get("CACHE_TTL_RESAMPLED_BARS", 300))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(Exception),
        after=lambda retry_state: logger.warning(
            f"Cache retry attempt {retry_state.attempt_number} failed"
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
        Fetch OHLCV bars from cache or database, resampling if needed.

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
            Exception: If cache or database fetch fails (retried automatically).
        """
        # Try resampled cache for non-1m timeframes
        if self.cache and timeframe != "1m":
            cache_key = f"ohlcv:{self.market}:{self.provider}:{self.symbol}:{timeframe}"
            try:
                cached_bars = await self.cache.get_resampled(cache_key)
                if cached_bars:
                    logger.debug(f"Fetched {len(cached_bars)} resampled bars from cache")
                    return self._filter_bars(cached_bars, since, before, limit)
            except Exception as e:
                logger.warning(f"Resampled cache fetch failed: {e}", exc_info=True)

        # Calculate 1m limit for resampling
        limit_1m = limit
        if timeframe != "1m":
            try:
                _, _, tf_period_ms = _parse_timeframe_str(timeframe)
                limit_1m = limit * (tf_period_ms // UNIT_MS["m"]) + (tf_period_ms // UNIT_MS["m"]) + 10
            except ValueError:
                logger.warning(f"Invalid timeframe '{timeframe}', using default limit")
                limit_1m = limit * 60  # Fallback: assume 1h timeframe

        one_m_since = since
        if not one_m_since and timeframe != "1m":
            one_m_since = before - (limit_1m * UNIT_MS["m"]) if before else int(time.time() * 1000) - (limit_1m * UNIT_MS["m"])

        # Fetch 1m bars
        bars = []
        if self.cache:
            try:
                bars = await self.cache.get_1m_bars(
                    self.market, self.provider, self.symbol, one_m_since, before, limit_1m
                )
                logger.debug(f"Fetched {len(bars)} 1m bars from cache")
            except Exception as e:
                logger.warning(f"1m cache fetch failed: {e}, falling back to database", exc_info=True)

        if not bars:
            bars = await fetch_ohlcv_from_db(
                self.market, self.provider, self.symbol, "1m", one_m_since, before, limit_1m
            )
            logger.debug(f"Fetched {len(bars)} 1m bars from database")

        # Resample and cache if needed
        if bars and timeframe != "1m":
            resampled_bars = self.resampler.resample(bars, timeframe)
            if self.cache:
                try:
                    cache_key = f"ohlcv:{self.market}:{self.provider}:{self.symbol}:{timeframe}"
                    await self.cache.set_resampled(cache_key, resampled_bars, self.resampled_ttl)
                    logger.debug(f"Cached {len(resampled_bars)} resampled bars for {timeframe}")
                except Exception as e:
                    logger.warning(f"Failed to cache resampled bars: {e}", exc_info=True)
            return self._filter_bars(resampled_bars, since, before, limit)

        return self._filter_bars(bars, since, before, limit)

    def _filter_bars(
        self,
        bars: List[Dict[str, Any]],
        since: Optional[int],
        before: Optional[int],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        Filter bars by time range and limit.

        Args:
            bars (List[Dict[str, Any]]): List of OHLCV bars.
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            before (Optional[int]): End timestamp in milliseconds (exclusive).
            limit (int): Maximum number of bars to return.

        Returns:
            List[Dict[str, Any]]: Filtered list of bars.
        """
        filtered = bars
        if since is not None:
            filtered = [b for b in filtered if b["timestamp"] >= since]
        if before is not None:
            filtered = [b for b in filtered if b["timestamp"] < before]
        if len(filtered) > limit:
            filtered = filtered[-limit:] if since is None else filtered[:limit]
        return filtered