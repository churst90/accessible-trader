# services/data_sources/cache_source.py

import logging
import time # Import time for current timestamp
from typing import Dict, List, Optional, Any
import asyncio # For asyncio.create_task

from quart import current_app
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from utils.db_utils import fetch_ohlcv_from_db
from utils.timeframes import UNIT_MS, _parse_timeframe_str

from .base import DataSource
from ..cache_manager import Cache # Correct import for Cache ABC (assuming it's in ..cache_manager)
from ..resampler import Resampler # Correct import for Resampler

logger = logging.getLogger("CacheSource")


class CacheSource(DataSource):
    """
    DataSource for fetching OHLCV bars from Redis cache with database fallback.

    This source is designed to be instantiated *per request* by the `MarketService`
    via the `DataOrchestrator`. It attempts to fetch resampled bars for non-1m timeframes
    from cache first. For 1m data or cache misses, it fetches 1m bars from the cache
    or database, resampling if needed. Resampled results are then stored back into the cache.

    Attributes:
        market (str): The market identifier (e.g., "crypto", "stocks").
        provider (str): The provider identifier (e.g., "binance", "alpaca").
        symbol (str): The trading pair symbol (e.g., "BTC/USD") for which this source is configured.
        cache (Optional[Cache]): Cache manager for Redis operations (shared instance).
        resampler (Resampler): Resampler for converting 1m bars to higher timeframes (shared instance).
        resampled_ttl (int): Time-to-live (in seconds) for cached resampled bars.
        default_1m_fetch_limit (int): Default limit when fetching 1m data if target limit is None or calculation fails.
    """

    def __init__(
        self,
        market: str,
        provider: str,
        symbol: str, # Symbol is now a required argument at initialization
        cache: Optional[Cache],
        resampler: Resampler,
    ):
        """
        Initialize the CacheSource.

        Args:
            market (str): The market identifier.
            provider (str): The provider identifier.
            symbol (str): The trading pair symbol.
            cache (Optional[Cache]): Cache manager instance (e.g., RedisCache). Can be None if cache is unavailable.
            resampler (Resampler): Resampler instance.

        Raises:
            ValueError: If market, provider, symbol, or resampler are invalid.
        """
        if not market or not provider:
            raise ValueError("market and provider must be non-empty strings")
        if not symbol:
            raise ValueError("symbol must be a non-empty string for CacheSource initialization")
        if not isinstance(resampler, Resampler):
            raise ValueError("resampler must be an instance of Resampler")

        self.market = market
        self.provider = provider
        self.symbol = symbol
        self.cache = cache
        self.resampler = resampler
        # Load TTL and default 1m fetch limit from app config
        self.resampled_ttl = int(current_app.config.get("CACHE_TTL_RESAMPLED_BARS", 300))
        self.default_1m_fetch_limit = int(current_app.config.get("DEFAULT_1M_FETCH_LIMIT_FOR_RESAMPLING", 1000))
        logger.debug(f"CacheSource initialized for {market}/{provider}/{symbol}.")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(Exception), # Retry on any Exception for cache/db ops
        after=lambda retry_state: logger.warning(
            f"CacheSource: Retry attempt {retry_state.attempt_number} for {retry_state.fn.__self__.symbol}/{retry_state.kwargs['timeframe']} failed. "
            f"Error: {retry_state.outcome.exception()}"
        ),
    )
    async def fetch_ohlcv(
        self,
        timeframe: str, # The requested timeframe (e.g., '5h')
        since: Optional[int],
        before: Optional[int],
        limit: int, # The target number of bars for 'timeframe' (e.g., 200)
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars from Redis cache or the database, resampling if needed.

        This method attempts to fulfill the request by first checking the cache for
        pre-resampled data (if `timeframe` is not "1m"). If a cache miss or `timeframe`
        is "1m", it then fetches 1-minute bars from the cache, falling back to the
        database if necessary. If 1-minute bars are fetched and `timeframe` is higher,
        they are resampled, and the resampled results are asynchronously stored back into the cache.

        Args:
            timeframe (str): The requested timeframe (e.g., "1m", "5m").
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            before (Optional[int]): End timestamp in milliseconds (exclusive).
            limit (int): Maximum number of bars to return for the requested timeframe.

        Returns:
            List[Dict[str, Any]]: List of OHLCV bars, sorted by timestamp ascending (oldest first).
                                  Returns an empty list if no data is found or errors occur.

        Raises:
            ValueError: If the timeframe is invalid or parsing fails.
            Exception: For critical errors during cache or database operations (handled by tenacity).
        """
        start_time = time.time()
        logger.debug(f"CacheSource: Starting fetch_ohlcv for {self.symbol}/{timeframe} (since={since}, before={before}, limit={limit}).")

        # Ensure timeframe is valid before proceeding to avoid parsing errors later
        try:
            _, _, target_period_ms = _parse_timeframe_str(timeframe)
            if target_period_ms <= 0:
                raise ValueError("Timeframe period must be positive.")
        except ValueError as e:
            logger.error(f"CacheSource: Invalid timeframe '{timeframe}': {e}.")
            raise ValueError(f"Invalid timeframe: {timeframe}") from e

        # 1. Try fetching directly from the resampled cache for non-1m timeframes
        if self.cache and timeframe != "1m":
            cache_key_resampled = f"ohlcv:{self.market}:{self.provider}:{self.symbol}:{timeframe}"
            try:
                # Cache.get_resampled handles deserialization and internal logging
                cached_resampled_bars = await self.cache.get_resampled(cache_key_resampled)
                if cached_resampled_bars:
                    logger.debug(f"CacheSource: Cache hit for resampled bars ({len(cached_resampled_bars)} bars) for {self.symbol}/{timeframe}.")
                    # Filter cached bars to match the requested range and limit
                    filtered_resampled_bars = self._filter_bars(cached_resampled_bars, since, before, limit)
                    logger.info(f"CacheSource: Returned {len(filtered_resampled_bars)} resampled bars from cache for {self.symbol}/{timeframe} in {time.time() - start_time:.2f}s.")
                    return filtered_resampled_bars
                else:
                    logger.debug(f"CacheSource: Resampled cache miss for {self.symbol}/{timeframe}.")
            except Exception as e:
                logger.warning(f"CacheSource: Resampled cache fetch failed for {self.symbol}/{timeframe}: {e}. Falling back to 1m data.", exc_info=True)
                # Continue to fetch 1m data on cache errors

        # 2. If we are here, either timeframe is "1m", or resampled cache missed/failed.
        # We need to fetch 1m data to either return it directly or to resample it.

        # Calculate how many 1m bars are needed to satisfy the 'limit' of the target 'timeframe'.
        limit_1m_to_fetch = limit # Default: if timeframe is 1m or calculation fails
        if timeframe != "1m":
            try:
                # Get periods in milliseconds for calculation
                _, _, target_period_ms = _parse_timeframe_str(timeframe)
                _, _, m1_period_ms = _parse_timeframe_str("1m")

                if m1_period_ms > 0 and target_period_ms >= m1_period_ms:
                    ratio = target_period_ms // m1_period_ms
                    # We need roughly 'limit' * ratio bars, plus a buffer for time boundary issues
                    calculated_1m_limit = limit * ratio + ratio + 200 # Add a buffer (e.g., 200 bars)
                    limit_1m_to_fetch = calculated_1m_limit
                    logger.debug(f"CacheSource: Calculated needed 1m bars ({limit_1m_to_fetch}) based on {timeframe} limit ({limit}).")
                elif target_period_ms < m1_period_ms:
                    logger.warning(f"CacheSource: Requested timeframe '{timeframe}' is smaller than 1m. Fetching with original limit {limit} bars of 1m.")
                    limit_1m_to_fetch = limit # If somehow fetching a larger TF to resample to a smaller one (unusual)
                else:
                    logger.warning(f"CacheSource: 1m period is zero or target period is smaller, cannot accurately calculate 1m fetch_limit. Using default 1m fetch limit ({self.default_1m_fetch_limit}).")
                    limit_1m_to_fetch = self.default_1m_fetch_limit # Fallback if calculation logic fails
            except ValueError as e:
                logger.warning(f"CacheSource: Invalid timeframe string for 1m period calculation ('{timeframe}'): {e}. Using default 1m fetch limit ({self.default_1m_fetch_limit}).", exc_info=True)
                limit_1m_to_fetch = self.default_1m_fetch_limit # Fallback on parsing errors
            except Exception as e:
                logger.error(f"CacheSource: Error calculating 1m fetch_limit for resampling: {e}. Using default 1m fetch limit ({self.default_1m_fetch_limit}).", exc_info=True)
                limit_1m_to_fetch = self.default_1m_fetch_limit # Fallback on unexpected error

        # Calculate the 'since' timestamp for the 1m data fetch.
        # If the original 'since' is None, estimate a 'since' that would cover
        # `limit_1m_to_fetch` bars ending around `before` (or now).
        one_m_since = since
        if one_m_since is None:
            try:
                _, _, fetch_period_ms = _parse_timeframe_str("1m")
                if fetch_period_ms > 0:
                    end_time_ms = before if before is not None else int(time.time() * 1000)
                    # Estimate start time by subtracting the duration of the bars to be fetched, plus a buffer
                    estimated_start_time_ms = end_time_ms - (limit_1m_to_fetch * fetch_period_ms) - fetch_period_ms
                    one_m_since = estimated_start_time_ms
                    logger.debug(f"CacheSource: Estimated one_m_since based on limit_1m: {one_m_since}ms.")
                else:
                    logger.warning("CacheSource: 1m period is zero, cannot estimate one_m_since based on limit. Passing None.")
                    one_m_since = None # Cannot estimate, pass None
            except ValueError:
                logger.warning(f"CacheSource: Invalid timeframe string for 1m 'since' calculation. Skipping estimation, passing None.", exc_info=True)
                one_m_since = None # Fallback

        # 3. Fetch 1m bars from cache
        bars_1m: List[Dict[str, Any]] = []
        if self.cache:
            try:
                # Pass the calculated 1m limit and range to the cache.
                bars_1m = await self.cache.get_1m_bars(
                    self.market, self.provider, self.symbol, one_m_since, before, limit_1m_to_fetch
                )
                if bars_1m:
                    logger.debug(f"CacheSource: Fetched {len(bars_1m)} 1m bars from cache for {self.symbol}.")
                else:
                    logger.debug(f"CacheSource: 1m cache miss for {self.symbol}. Fetching from database.")
            except Exception as e:
                logger.warning(f"CacheSource: 1m cache fetch failed for {self.symbol}: {e}. Falling back to database.", exc_info=True)

        # 4. If cache fetch failed or returned no bars, fetch from database
        if not bars_1m:
            try:
                # Pass the calculated 1m limit and range to the DB fetch.
                # `Workspace_ohlcv_from_db` supports since/before/limit filtering.
                bars_1m = await fetch_ohlcv_from_db(
                    self.market, self.provider, self.symbol, "1m", one_m_since, before, limit_1m_to_fetch
                )
                if bars_1m:
                    logger.debug(f"CacheSource: Fetched {len(bars_1m)} 1m bars from database for {self.symbol}.")
                else:
                    logger.debug(f"CacheSource: No 1m bars found in database for {self.symbol}.")
            except Exception as e:
                logger.error(f"CacheSource: 1m database fetch failed for {self.symbol}: {e}. Returning empty list.", exc_info=True)
                return [] # If DB fetch also fails, return empty list

        # 5. If we fetched 1m bars and need to resample for a higher timeframe
        if bars_1m and timeframe != "1m":
            logger.debug(f"CacheSource: Resampling {len(bars_1m)} 1m bars to {timeframe} for {self.symbol}.")
            resampled_bars = self.resampler.resample(bars_1m, timeframe)
            logger.debug(f"CacheSource: Resampling resulted in {len(resampled_bars)} {timeframe} bars for {self.symbol}.")

            # Asynchronously store the resampled bars in cache (fire and forget)
            if self.cache and resampled_bars: # Only store if there are bars to store
                try:
                    cache_key_resampled = f"ohlcv:{self.market}:{self.provider}:{self.symbol}:{timeframe}"
                    asyncio.create_task(
                        self.cache.set_resampled(cache_key_resampled, resampled_bars, self.resampled_ttl),
                        name=f"CacheResampledStore_{self.symbol}_{timeframe}"
                    )
                    logger.debug(f"CacheSource: Scheduled caching of {len(resampled_bars)} resampled bars for {timeframe}.")
                except Exception as e:
                    logger.warning(f"CacheSource: Failed to schedule caching of resampled bars: {e}", exc_info=True)

            # Return the resampled bars. The DataOrchestrator will apply final filtering.
            logger.info(f"CacheSource: Returned {len(resampled_bars)} resampled bars for {self.symbol}/{timeframe} in {time.time() - start_time:.2f}s.")
            return resampled_bars

        # 6. If timeframe was "1m", return the fetched 1m bars after filtering by the original limit.
        # This filter is necessary here because the `get_1m_bars` or `Workspace_ohlcv_from_db` might
        # return more bars than the requested `limit` if `one_m_since` was estimated to cover enough
        # data for resampling purposes, but the request was actually for a specific `limit` of 1m bars.
        final_bars = self._filter_bars(bars_1m, since, before, limit)
        logger.info(f"CacheSource: Returned {len(final_bars)} 1m bars for {self.symbol}/{timeframe} in {time.time() - start_time:.2f}s.")
        return final_bars

    def _filter_bars(
        self, bars: List[Dict[str, Any]], since: Optional[int], before: Optional[int], limit: int
    ) -> List[Dict[str, Any]]:
        """
        Filter a list of OHLCV bars by a specified time range and limit.

        This helper method ensures that the returned list of bars adheres to the
        `since`, `before`, and `limit` parameters after data has been fetched
        (e.g., from cache or DB).

        Args:
            bars (List[Dict[str, Any]]): The input list of OHLCV bars. Assumed to be sorted by timestamp.
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            before (Optional[int]): End timestamp in milliseconds (exclusive).
            limit (int): Maximum number of bars to return.

        Returns:
            List[Dict[str, Any]]: The filtered list of bars.
        """
        # Ensure bars are sorted for correct filtering and limit application.
        # Although data from DB/PluginSource is usually sorted, data from generic cache
        # might not strictly be, so sorting here adds robustness.
        # Use a copy to avoid modifying the original list passed in.
        filtered = sorted(bars, key=lambda b: b.get("timestamp", 0))

        initial_len = len(filtered)

        # Apply 'since' filter (inclusive)
        if since is not None:
            filtered = [b for b in filtered if b.get("timestamp", float('-inf')) >= since]
            logger.debug(f"CacheSource._filter_bars: Applied 'since' filter ({since}ms). {len(filtered)} bars remain.")

        # Apply 'before' filter (exclusive)
        if before is not None:
            filtered = [b for b in filtered if b.get("timestamp", float('inf')) < before]
            logger.debug(f"CacheSource._filter_bars: Applied 'before' filter ({before}ms). {len(filtered)} bars remain.")

        # Apply limit. The logic depends on whether 'since' was provided.
        # If 'since' is None, it means the client wants the `limit` most recent bars.
        # If 'since' is provided, it means the client wants `limit` bars starting from 'since'.
        if len(filtered) > limit:
            if since is None:
                # If fetching the latest N bars, take the last 'limit' bars
                filtered = filtered[-limit:]
                logger.debug(f"CacheSource._filter_bars: Applied limit ({limit}) for 'latest N' request: took last {len(filtered)} bars.")
            else:
                # If fetching from a specific 'since', take the first 'limit' bars
                filtered = filtered[:limit]
                logger.debug(f"CacheSource._filter_bars: Applied limit ({limit}) for 'since' request: took first {len(filtered)} bars.")
        
        logger.debug(f"CacheSource._filter_bars: Filtered {initial_len} bars down to {len(filtered)}.")
        return filtered