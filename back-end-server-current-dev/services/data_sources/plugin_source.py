# services/data_sources/plugin_source.py

import logging
import time # Added import for time.time()
from typing import Dict, List, Optional, Any

from quart import current_app
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from plugins.base import MarketPlugin, PluginError
from utils.db_utils import insert_ohlcv_to_db
from utils.timeframes import UNIT_MS, _parse_timeframe_str # Added _parse_timeframe_str

from .base import DataSource
# Assuming Cache is imported elsewhere or handled by forward reference
# from services.cache_manager import Cache # Example if direct import needed for type hints outside methods

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
            ValueError: If market, provider, or sources are invalid.
        """
        # Removed symbol check here, as it's set dynamically per fetch now.
        if not market or not provider:
            raise ValueError("market and provider must be non-empty strings")
        self.market = market
        self.provider = provider
        self.symbol = symbol # Keep initial symbol, but expect it to be updated
        self.plugin = plugin
        self.cache = cache
        self.resampler = resampler
        self.chunk_size = int(current_app.config.get("DEFAULT_PLUGIN_CHUNK_SIZE", 500))

    # Note: symbol attribute is updated by DataOrchestrator before calling fetch_ohlcv

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(PluginError),
        after=lambda retry_state: logger.warning(
            f"Plugin retry attempt {retry_state.attempt_number} failed for {self.symbol}/{self.timeframe}" # Added symbol/timeframe for context
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
        Fetch OHLCV bars from the plugin, preferring native timeframe if supported,
        falling back to 1-minute bars and resampling.
        """
        if not self.symbol:
             logger.error("PluginSource: symbol is not set before fetch_ohlcv.")
             return [] # Cannot fetch without a symbol


        # Determine the timeframe to fetch from the plugin (always 1m for CryptoPlugin unless native is supported)
        try:
            # Assuming self.plugin.supported_timeframes handles potential errors or lack of support
            supported_plugin_tfs = await self.plugin.supported_timeframes(self.provider, self.symbol)
            # Use the requested timeframe if the plugin supports it natively, otherwise fall back to 1m
            fetch_timeframe = timeframe if timeframe in supported_plugin_tfs else '1m'
            if timeframe != fetch_timeframe:
                 logger.debug(f"Plugin '{self.plugin.__class__.__name__}' does not natively support '{timeframe}', fetching '{fetch_timeframe}' for resampling.")
        except Exception as e:
            logger.warning(f"Could not get supported timeframes for {self.provider}/{self.symbol} from plugin: {e}. Assuming fetch_timeframe is 1m if requested timeframe is not 1m.", exc_info=True)
            fetch_timeframe = '1m' if timeframe != '1m' else '1m' # Default to 1m fallback logic if supported check fails


        # Calculate how many bars of 'fetch_timeframe' are needed to satisfy the 'limit' of 'timeframe'
        # This is crucial for resampling higher timeframes from lower ones.
        fetch_limit = limit # Default: if timeframe matches fetch_timeframe or fallback calculation fails

        if timeframe != fetch_timeframe:
            try:
                # Get periods in milliseconds for calculation
                _, _, target_period_ms = _parse_timeframe_str(timeframe)
                _, _, fetch_period_ms = _parse_timeframe_str(fetch_timeframe)

                if fetch_period_ms > 0 and target_period_ms >= fetch_period_ms:
                    # Calculate the ratio of the target timeframe period to the fetched timeframe period
                    ratio = target_period_ms // fetch_period_ms
                    # We need roughly 'limit' * ratio bars + a buffer to cover time boundary issues
                    fetch_limit = limit * ratio + ratio + 200 # Add a buffer (e.g., 200 bars)
                    logger.debug(f"Calculated needed {fetch_timeframe} bars based on {timeframe} limit {limit}: {fetch_limit}")
                elif target_period_ms < fetch_period_ms:
                     logger.warning(f"Requested timeframe '{timeframe}' is smaller than plugin's fetch timeframe '{fetch_timeframe}'. Fetching with limit {limit}.")
                     fetch_limit = limit # If somehow fetching a larger TF to resample to a smaller one (unusual)
                else:
                    logger.warning(f"Fetch timeframe period is zero for '{fetch_timeframe}' or target period is smaller, cannot accurately calculate fetch_limit.")
                    # Fallback to original limit

            except ValueError:
                logger.warning(f"Invalid timeframe string for period calculation ('{timeframe}' or '{fetch_timeframe}'), using default fetch_limit = limit.", exc_info=True)
                fetch_limit = limit # Fallback

        # Clamp the calculated fetch_limit by the plugin's max chunk size to avoid excessively large single requests
        actual_plugin_fetch_limit = min(fetch_limit, self.chunk_size) # Use self.chunk_size as the max plugin limit

        logger.debug(f"PluginSource: Fetching {actual_plugin_fetch_limit} bars of {fetch_timeframe} for {self.symbol} (requested {timeframe} limit {limit}) since {since} before {before}")


        # Calculate 'since' timestamp for the plugin request
        # If the original 'since' is None, estimate a 'since' timestamp that would cover
        # 'actual_plugin_fetch_limit' bars ending around 'before' (or now).
        fetch_since = since
        # Only estimate fetch_since if the original 'since' is None
        if fetch_since is None:
            try:
                 _, _, fetch_period_ms = _parse_timeframe_str(fetch_timeframe)
                 if fetch_period_ms > 0:
                     # Calculate the estimated start time based on the number of bars we are about to fetch
                     # Use 'before' if provided, otherwise use current time
                     end_time_ms = before if before is not None else int(time.time() * 1000)
                     # Estimate start time by subtracting the duration of the bars to be fetched
                     # Add a buffer of one period to ensure the 'before' boundary is handled correctly
                     estimated_start_time_ms = end_time_ms - (actual_plugin_fetch_limit * fetch_period_ms) - fetch_period_ms
                     fetch_since = estimated_start_time_ms
                     logger.debug(f"PluginSource: Estimated fetch_since based on limit and timeframe: {fetch_since}")
                 else:
                     logger.warning(f"Fetch timeframe period is zero for '{fetch_timeframe}', cannot estimate fetch_since based on limit.")
                     fetch_since = None # Cannot estimate, pass None or rely on plugin default
            except ValueError:
                 logger.warning(f"Invalid fetch timeframe '{fetch_timeframe}' for since calculation, skipping estimation.", exc_info=True)
                 fetch_since = None # Fallback


        try:
            bars = await self.plugin.fetch_historical_ohlcv(
                provider=self.provider,
                symbol=self.symbol,
                timeframe=fetch_timeframe, # Pass the actual timeframe being fetched (e.g., '1m')
                since=fetch_since,  # Use the calculated fetch_since (can still be None if calculation failed or original since was None)
                limit=actual_plugin_fetch_limit, # Use the calculated and clamped limit for the 1m fetch
                # Pass original params if needed, but typically not for core OHLCV fetch
                # params=params # Example
            )
            if not bars:
                logger.debug(f"Plugin returned no data for {fetch_timeframe} for {self.symbol} in range {since}-{before}")
                return []

            # Sort bars by timestamp ascending, important for resampling
            bars.sort(key=lambda b: b.get("timestamp", 0))

            # Store fetched bars (these are fetch_timeframe bars, e.g. 1m)
            # This logic is correct; it stores the raw data from the plugin
            await insert_ohlcv_to_db(self.market, self.provider, self.symbol, fetch_timeframe, bars)
            # Only store 1m bars in the dedicated 1m cache
            if self.cache and fetch_timeframe == '1m':
                try:
                    await self.cache.store_1m_bars(self.market, self.provider, self.symbol, bars)
                    logger.debug(f"Stored {len(bars)} {fetch_timeframe} bars in cache")
                except Exception as e:
                    logger.warning(f"Failed to store {fetch_timeframe} bars in cache: {e}", exc_info=True)


            # Resample if needed
            if fetch_timeframe != timeframe and bars: # Ensure bars is not empty before resampling
                logger.debug(f"Resampling {len(bars)} {fetch_timeframe} bars to {timeframe}")
                resampled_bars = self.resampler.resample(bars, timeframe) # 'resampled_bars' holds the resampled data
                logger.debug(f"Resampling resulted in {len(resampled_bars)} {timeframe} bars")
                # Return the resampled bars. Final filtering will happen in DataOrchestrator/CacheSource.
                return resampled_bars

            # If no resampling needed (because fetch_timeframe == timeframe), return the fetched bars directly
            logger.debug(f"PluginSource returning {len(bars)} {timeframe} bars (no resampling needed)")
            return bars # Return the original bars if timeframe was 1m


        except PluginError as e:
            # Re-raise plugin errors so they can be handled by the caller (DataOrchestrator)
            logger.error(f"Plugin fetch failed for {self.symbol}/{timeframe}: {e}", exc_info=True)
            raise

        except Exception as e:
            # Catch any other unexpected errors during the fetch or resampling process
            logger.error(f"An unexpected error occurred in PluginSource.fetch_ohlcv for {self.symbol}/{timeframe}: {e}", exc_info=True)
            # Depending on how you want unhandled errors to propagate, you might raise a specific error
            # or allow DataOrchestrator's broader exception handling to catch it. Re-raising as PluginError is an option.
            raise PluginError(f"Unexpected error in PluginSource for {self.symbol}/{timeframe}: {e}") from e
