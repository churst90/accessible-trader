# services/data_sources/cache_source.py

import logging
import time # Import time for current timestamp
from typing import Dict, List, Optional, Any

from quart import current_app
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from utils.db_utils import fetch_ohlcv_from_db # Also fetch_historical_ohlcv_from_db might be used depending on logic
from utils.timeframes import UNIT_MS, _parse_timeframe_str # Import _parse_timeframe_str

from .base import DataSource
from ..cache_manager import Cache # Correct import for Cache ABC (assuming it's in ..cache_manager)
from ..resampler import Resampler # Correct import for Resampler

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
        cache (Optional[Cache]): Cache manager for Redis operations.
        resampler (Resampler): Resampler for converting 1m bars to higher timeframes.
        resampled_ttl (int): TTL for cached resampled bars (seconds).
        default_1m_fetch_limit (int): Default limit when fetching 1m if target limit is None or calculation fails.
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
            cache (Optional[Cache]): Cache manager instance.
            resampler (Resampler): Resampler instance.

        Raises:
            ValueError: If market or provider are invalid.
        """
        # Removed symbol check here, as it's set dynamically per fetch now.
        if not market or not provider:
            raise ValueError("market and provider must be non-empty strings")
        self.market = market
        self.provider = provider
        self.symbol = symbol # Keep initial symbol, but expect it to be updated
        self.cache = cache
        self.resampler = resampler
        self.resampled_ttl = int(current_app.config.get("CACHE_TTL_RESAMPLED_BARS", 300))
        # Add a configuration for a default large 1m fetch limit if needed
        self.default_1m_fetch_limit = int(current_app.config.get("DEFAULT_1M_FETCH_LIMIT_FOR_RESAMPLING", 1000))


    # Note: symbol attribute is updated by DataOrchestrator before calling fetch_ohlcv

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(Exception), # Retry on any Exception for cache/db ops
        after=lambda retry_state: logger.warning(
            f"CacheSource retry attempt {retry_state.attempt_number} failed for {self.symbol}/{self.timeframe}" # Added symbol/timeframe for context
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
        Fetch OHLCV bars from cache or database, resampling if needed.
        """
        if not self.symbol:
             logger.error("CacheSource: symbol is not set before fetch_ohlcv.")
             return [] # Cannot fetch without a symbol

        # Ensure timeframe is valid before proceeding
        try:
             _, _, target_period_ms = _parse_timeframe_str(timeframe)
             if target_period_ms <= 0:
                  raise ValueError("Timeframe period must be positive.")
        except ValueError as e:
             logger.error(f"CacheSource: Invalid timeframe '{timeframe}': {e}")
             raise ValueError(f"Invalid timeframe: {timeframe}") from e # Re-raise as ValueError


        # Try resampled cache for non-1m timeframes
        if self.cache and timeframe != "1m":
            cache_key = f"ohlcv:{self.market}:{self.provider}:{self.symbol}:{timeframe}"
            try:
                # Note: get_resampled should handle deserialization errors internally with logging
                cached_bars = await self.cache.get_resampled(cache_key)
                if cached_bars:
                    logger.debug(f"CacheSource: Fetched {len(cached_bars)} resampled bars for {timeframe} from cache for {self.symbol}")
                    # The bars from cache might not exactly match the requested time range/limit,
                    # so we filter them here before returning.
                    return self._filter_bars(cached_bars, since, before, limit)
                else:
                    logger.debug(f"CacheSource: Resampled cache miss for {self.symbol}/{timeframe}")
            except Exception as e:
                logger.warning(f"CacheSource: Resampled cache fetch failed for {self.symbol}/{timeframe}: {e}", exc_info=True)
                # Continue to fetch 1m data on cache errors


        # If we are here, either timeframe is 1m, or resampled cache missed/failed.
        # We need to fetch 1m data to return (if timeframe is 1m) or to resample.

        # Calculate how many 1m bars are needed to satisfy the 'limit' of 'timeframe'
        # This is crucial for resampling higher timeframes from lower ones.
        limit_1m = limit # Default: if timeframe is 1m or fallback calculation fails

        if timeframe != "1m":
            try:
                # Get periods in milliseconds for calculation
                _, _, target_period_ms = _parse_timeframe_str(timeframe)
                _, _, m1_period_ms = _parse_timeframe_str("1m")

                if m1_period_ms > 0 and target_period_ms >= m1_period_ms:
                    # Calculate the ratio of the target timeframe period to the 1m timeframe period
                    ratio = target_period_ms // m1_period_ms
                    # We need roughly 'limit' * ratio bars + a buffer to cover time boundary issues
                    # Use the original 'limit' requested for the *target* timeframe.
                    calculated_1m_limit = limit * ratio + ratio + 200 # Add a buffer (e.g., 200 bars)
                    limit_1m = calculated_1m_limit
                    logger.debug(f"CacheSource: Calculated needed 1m bars based on {timeframe} limit {limit}: {limit_1m}")
                elif target_period_ms < m1_period_ms:
                     logger.warning(f"CacheSource: Requested timeframe '{timeframe}' is smaller than 1m. Fetching with original limit {limit}.")
                     limit_1m = limit # If somehow fetching a larger TF to resample to a smaller one (unusual)
                else:
                    logger.warning(f"CacheSource: 1m period is zero or target period is smaller, cannot accurately calculate 1m fetch_limit.")
                    # Fallback to a default reasonable number of 1m bars if calculation logic fails
                    limit_1m = self.default_1m_fetch_limit


            except ValueError:
                logger.warning(f"CacheSource: Invalid timeframe string for 1m period calculation ('{timeframe}'), using default 1m fetch_limit.", exc_info=True)
                # Fallback to a default reasonable number of 1m bars if parsing fails
                limit_1m = self.default_1m_fetch_limit
            except Exception as e:
                logger.error(f"CacheSource: Error calculating 1m fetch_limit for resampling: {e}", exc_info=True)
                # Fallback on unexpected error
                limit_1m = self.default_1m_fetch_limit

        # Calculate the time range for the 1m data fetch
        one_m_since = since
        # If the original 'since' is None, estimate a 'since' timestamp that would cover
        # 'limit_1m' bars ending around 'before' (or now).
        if one_m_since is None:
             try:
                 _, _, fetch_period_ms = _parse_timeframe_str("1m")
                 if fetch_period_ms > 0:
                     # Calculate the estimated start time based on the number of 1m bars we are about to fetch
                     end_time_ms = before if before is not None else int(time.time() * 1000)
                     # Estimate start time by subtracting the duration of the bars to be fetched
                     # Add a buffer of one period
                     estimated_start_time_ms = end_time_ms - (limit_1m * fetch_period_ms) - fetch_period_ms
                     one_m_since = estimated_start_time_ms
                     logger.debug(f"CacheSource: Estimated one_m_since based on limit_1m: {one_m_since}")
                 else:
                      logger.warning("CacheSource: 1m period is zero, cannot estimate one_m_since based on limit.")
                      one_m_since = None # Cannot estimate, pass None
             except ValueError:
                  logger.warning(f"CacheSource: Invalid timeframe string for 1m since calculation, skipping estimation.", exc_info=True)
                  one_m_since = None # Fallback


        # Fetch 1m bars from cache
        bars = []
        if self.cache:
            try:
                # Pass the calculated 1m limit and range
                bars = await self.cache.get_1m_bars(
                    self.market, self.provider, self.symbol, one_m_since, before, limit_1m
                )
                logger.debug(f"CacheSource: Fetched {len(bars)} 1m bars from cache for {self.symbol}")
            except Exception as e:
                logger.warning(f"CacheSource: 1m cache fetch failed for {self.symbol}: {e}, falling back to database", exc_info=True)

        # If cache fetch failed or returned no bars, fetch from database
        if not bars:
            try:
                 # Pass the calculated 1m limit and range to DB fetch
                 bars = await fetch_ohlcv_from_db( # Or fetch_historical_ohlcv_from_db depending on exact need
                     self.market, self.provider, self.symbol, "1m", one_m_since, before, limit_1m
                 )
                 logger.debug(f"CacheSource: Fetched {len(bars)} 1m bars from database for {self.symbol}")
            except Exception as e:
                 logger.error(f"CacheSource: 1m database fetch failed for {self.symbol}: {e}", exc_info=True)
                 # If DB fetch also fails, return empty list
                 return []


        # If we fetched 1m bars, resample and cache if needed
        if bars and timeframe != "1m":
            logger.debug(f"CacheSource: Resampling {len(bars)} 1m bars to {timeframe} for {self.symbol}")
            resampled_bars = self.resampler.resample(bars, timeframe)
            logger.debug(f"CacheSource: Resampling resulted in {len(resampled_bars)} {timeframe} bars for {self.symbol}")

            # Cache the resampled bars (fire and forget)
            if self.cache:
                try:
                    cache_key = f"ohlcv:{self.market}:{self.provider}:{self.symbol}:{timeframe}"
                    # asyncio.create_task is generally preferred for fire-and-forget in async methods
                    import asyncio
                    asyncio.create_task(
                        self.cache.set_resampled(cache_key, resampled_bars, self.resampled_ttl),
                        name=f"CacheResampled_{self.symbol}_{timeframe}"
                    )
                    logger.debug(f"CacheSource: Scheduled caching of {len(resampled_bars)} resampled bars for {timeframe}")
                except Exception as e:
                    logger.warning(f"CacheSource: Failed to schedule caching of resampled bars: {e}", exc_info=True)

            # Return the resampled bars. Final filtering will happen in DataOrchestrator.
            # The _filter_bars call here in CacheSource is redundant if DataOrchestrator
            # always filters the merged results anyway. Let's rely on Orchestrator.
            # return self._filter_bars(resampled_bars, since, before, limit) # Removed redundant filtering

            return resampled_bars # Return the resampled bars

        # If timeframe was 1m, return the fetched 1m bars after filtering by original limit
        # The _filter_bars call here is necessary for 1m timeframe requests that come to CacheSource
        return self._filter_bars(bars, since, before, limit)


    def _filter_bars(
        self, bars: List[Dict[str, Any]], since: Optional[int], before: Optional[int], limit: int
    ) -> List[Dict[str, Any]]:
        """
        Filter bars by time range and limit.

        Args:
            bars (List[Dict[str, Any]]): List of OHLCV bars.
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            before (Optional[int]): End timestamp in milliseconds (exclusive).
            limit (int): Maximum number of bars to return.

        Returns:
            List[Dict[str, Any]]): Filtered list of bars.
        """
        # Ensure bars are sorted for correct limit application
        # Although DataOrchestrator sorts, filtering here might happen earlier
        # for cached resampled data.
        filtered = sorted(bars, key=lambda b: b.get("timestamp", 0))

        if since is not None:
            filtered = [b for b in filtered if b.get("timestamp", float('-inf')) >= since]
        if before is not None:
            filtered = [b for b in filtered if b.get("timestamp", float('inf')) < before]

        # Apply limit based on whether fetching from the beginning (since is None) or a specific point
        if len(filtered) > limit:
             if since is None:
                  # If fetching the latest N bars, take the last 'limit' bars
                  filtered = filtered[-limit:]
             else:
                  # If fetching from a specific 'since', take the first 'limit' bars
                  filtered = filtered[:limit]
        # logger.debug(f"Applied _filter_bars: {len(filtered)} bars remain from input {len(bars)}") # Can be noisy
        return filtered

