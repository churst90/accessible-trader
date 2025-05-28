# services/data_sources/plugin_source.py

from datetime import datetime, timezone
import logging
import time
from typing import Dict, List, Optional, Any
import asyncio # For asyncio.create_task

from quart import current_app
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from plugins.base import MarketPlugin, PluginError
from utils.db_utils import insert_ohlcv_to_db
from utils.timeframes import UNIT_MS, _parse_timeframe_str

from .base import DataSource

logger = logging.getLogger("PluginSource")


class PluginSource(DataSource):
    """
    DataSource for fetching OHLCV bars from external plugins.

    This source is designed to be instantiated *per request* by the `MarketService`
    via the `DataOrchestrator`. This allows it to receive a specific `MarketPlugin`
    instance that might be configured with user-specific API keys.

    It fetches bars using the plugin's native timeframe support when available,
    falling back to 1-minute bars and resampling if necessary. It validates symbols
    and timeframes before fetching, leverages market metadata to optimize requests,
    and stores fetched bars in the database and cache. It automatically adjusts fetch
    chunk sizes based on exchange-specific limits.

    Attributes:
        market (str): The market identifier (e.g., "crypto", "stocks").
        provider (str): The provider identifier (e.g., "binance", "alpaca").
        symbol (str): The trading pair symbol (e.g., "BTC/USD") for which this source is configured.
        plugin (MarketPlugin): The specific plugin instance for data fetching. This instance
                                is typically created by `MarketService` and may contain user API keys.
        cache (Optional[Cache]): Cache manager for storing bars (shared instance).
        resampler (Resampler): Resampler for converting 1m bars to higher timeframes (shared instance).
        chunk_size (int): Default maximum number of bars to fetch per plugin request if plugin limit is unavailable.
    """

    def __init__(
        self,
        market: str,
        provider: str,
        symbol: str, # Symbol is now a required argument at initialization
        plugin: MarketPlugin, # Expects an already instantiated plugin instance
        cache: Optional["Cache"],
        resampler: "Resampler",
    ):
        """
        Initialize the PluginSource.

        Args:
            market (str): The market identifier.
            provider (str): The provider identifier.
            symbol (str): The trading pair symbol.
            plugin (MarketPlugin): An instantiated `MarketPlugin` object, potentially configured
                                    with user-specific API keys.
            cache (Optional[Cache]): Cache manager instance (e.g., RedisCache).
            resampler (Resampler): Resampler instance.

        Raises:
            ValueError: If market, provider, symbol, or plugin are invalid or not provided.
        """
        if not market or not provider:
            raise ValueError("market and provider must be non-empty strings")
        if not symbol:
            raise ValueError("symbol must be a non-empty string for PluginSource initialization")
        if not isinstance(plugin, MarketPlugin): # Ensure it's a proper plugin instance
            raise ValueError("plugin must be an instance of MarketPlugin")

        self.market = market
        self.provider = provider
        self.symbol = symbol
        self.plugin = plugin
        self.cache = cache
        self.resampler = resampler
        # Load default chunk size from app config
        self.chunk_size = int(current_app.config.get("DEFAULT_PLUGIN_CHUNK_SIZE", 500))
        logger.debug(f"PluginSource initialized for {market}/{provider}/{symbol}.")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(PluginError),
        after=lambda retry_state: logger.warning(
            # Fix: Access the instance via retry_state.args[0]
            f"PluginSource: Retry attempt {retry_state.attempt_number} for {retry_state.args[0].symbol}/{retry_state.args[1]} failed. "
            f"Error: {retry_state.outcome.exception()}"
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
        Fetch OHLCV bars from the configured `MarketPlugin` instance.

        This method attempts to fetch data using the plugin's native timeframe support.
        If the native timeframe is not supported or historical data availability is limited,
        it may fall back to fetching 1-minute bars for later resampling. It performs
        symbol and timeframe validation, and dynamically adjusts fetch chunk sizes
        based on plugin limits. Fetched bars are stored in the database and cache.

        Args:
            timeframe (str): The requested timeframe (e.g., "5m", "1h").
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            before (Optional[int]): End timestamp in milliseconds (exclusive).
            limit (int): Maximum number of bars to return for the requested timeframe.

        Returns:
            List[Dict[str, Any]]: List of OHLCV bars, each with standard OHLCV keys and a 'timestamp'.
                                  Bars are sorted by timestamp ascending (oldest first).

        Raises:
            PluginError: If the plugin fetch fails or if the symbol/timeframe is invalid
                         after all retries.
            ValueError: If internal calculations for timeframes or limits are invalid.
        """
        start_time = time.time()
        logger.debug(f"PluginSource: Starting fetch_ohlcv for {self.provider}/{self.symbol}/{timeframe} (since={since}, before={before}, limit={limit})")

        # 1. Validate the symbol for the current plugin instance
        try:
            is_valid_symbol = await self.plugin.validate_symbol(self.provider, self.symbol)
            if not is_valid_symbol:
                logger.error(f"PluginSource: Symbol {self.symbol} is invalid or inactive for provider {self.provider}.")
                raise PluginError(f"Invalid or inactive symbol: {self.symbol}")
        except PluginError as e: # Re-raise specific plugin errors
            logger.error(f"PluginSource: Error validating symbol {self.symbol} for {self.provider}: {e}", exc_info=True)
            raise
        except Exception as e: # Catch any other unexpected errors during validation
            logger.error(f"PluginSource: Unexpected error validating symbol {self.symbol} for {self.provider}: {e}", exc_info=True)
            raise PluginError(f"Failed to validate symbol {self.symbol}: {e}") from e

        # 2. Fetch and log market info and server time for debugging/monitoring
        # These are informational and don't directly block the fetch flow.
        try:
            market_info = await self.plugin.get_market_info(self.provider, self.symbol)
            logger.debug(f"PluginSource: Market info for {self.provider}/{self.symbol}: {market_info}")
        except Exception as e:
            logger.warning(f"PluginSource: Failed to fetch market info for {self.provider}/{self.symbol}: {e}", exc_info=True)
            market_info = {} # Ensure market_info is always a dict

        try:
            server_time = await self.plugin.fetch_server_time(self.provider)
            if server_time is not None:
                logger.debug(f"PluginSource: Server time for {self.provider}: {server_time}ms (local time: {int(time.time() * 1000)}ms).")
            else:
                logger.debug(f"PluginSource: Server time unavailable for {self.provider}.")
        except Exception as e:
            logger.warning(f"PluginSource: Failed to fetch server time for {self.provider}: {e}", exc_info=True)

        # 3. Determine the actual timeframe to fetch from the plugin
        # Prefer the requested timeframe if natively supported and has sufficient history.
        fetch_timeframe = timeframe
        try:
            is_supported_natively = await self.plugin.validate_timeframe(self.provider, self.symbol, timeframe)
            if not is_supported_natively:
                logger.warning(f"PluginSource: Requested timeframe '{timeframe}' not natively supported by {self.provider}/{self.symbol}. Falling back to '1m'.")
                fetch_timeframe = "1m"
            else:
                logger.debug(f"PluginSource: Timeframe '{timeframe}' is natively supported by {self.provider}.")
        except PluginError as e:
            logger.error(f"PluginSource: Error validating timeframe {timeframe} for {self.provider}/{self.symbol}: {e}", exc_info=True)
            fetch_timeframe = "1m" # Fallback on error during validation
        except Exception as e:
            logger.warning(f"PluginSource: Unexpected error validating timeframe {timeframe} for {self.provider}/{self.symbol}: {e}", exc_info=True)
            fetch_timeframe = "1m" # Fallback to 1m on unexpected error

        # 4. Check historical data availability to decide if fallback to 1m is needed due to history depth
        target_oldest_ms = since if since is not None else int(time.time() * 1000) - 30 * 24 * 60 * 60 * 1000 # Default to 30 days if 'since' is not provided
        try:
            earliest_available_ms = await self.plugin.get_historical_data_availability(self.provider, self.symbol, fetch_timeframe)
            if earliest_available_ms is not None and fetch_timeframe != "1m" and earliest_available_ms > target_oldest_ms:
                logger.warning(
                    f"PluginSource: Historical data for {self.provider}/{self.symbol}/{fetch_timeframe} only available from {earliest_available_ms}ms, "
                    f"but requested data from {target_oldest_ms}ms. Falling back to '1m' for deeper history (if available)."
                )
                fetch_timeframe = "1m" # Switch to 1m if the native TF doesn't cover the requested 'since'
        except PluginError as e:
            logger.error(f"PluginSource: PluginError checking historical availability for {self.provider}/{self.symbol}: {e}", exc_info=True)
            # Proceed with current fetch_timeframe, hoping for the best or relying on the overall fetch to fail
        except Exception as e:
            logger.warning(f"PluginSource: Unexpected error checking historical availability for {self.provider}/{self.symbol}: {e}", exc_info=True)
            # Continue with current fetch_timeframe

        # 5. Determine the actual chunk size for plugin requests
        # This is the maximum number of bars the plugin can return in one API call.
        actual_plugin_fetch_limit = self.chunk_size # Start with default configured chunk size
        try:
            max_fetch_limit = await self.plugin.get_max_fetch_limit(self.provider, self.symbol, fetch_timeframe)
            if max_fetch_limit is not None and max_fetch_limit > 0:
                actual_plugin_fetch_limit = max_fetch_limit
                logger.debug(f"PluginSource: Using plugin-provided fetch limit for {self.provider}/{fetch_timeframe}: {actual_plugin_fetch_limit} bars.")
            else:
                logger.warning(
                    f"PluginSource: Plugin {self.plugin.__class__.__name__} returned an invalid or None max fetch limit for "
                    f"{self.provider}/{self.symbol}/{fetch_timeframe}. Using default chunk size: {self.chunk_size}."
                )
        except PluginError as e:
            logger.error(f"PluginSource: PluginError getting max fetch limit for {self.provider}/{self.symbol}/{fetch_timeframe}: {e}", exc_info=True)
            # Use default chunk_size on error
        except Exception as e:
            logger.warning(f"PluginSource: Unexpected error getting max fetch limit for {self.provider}/{self.symbol}/{fetch_timeframe}: {e}", exc_info=True)
            # Use default chunk_size on unexpected error

        # 6. Calculate the number of `Workspace_timeframe` bars needed to satisfy the `limit` of `timeframe`
        # This is particularly important when resampling from a lower timeframe (e.g., fetching 1m to resample to 5m).
        fetch_limit = limit # Initialize with the requested limit
        if fetch_timeframe != timeframe:
            try:
                # Parse periods in milliseconds for the target and fetch timeframes
                _, _, target_period_ms = _parse_timeframe_str(timeframe)
                _, _, fetch_period_ms = _parse_timeframe_str(fetch_timeframe)

                if fetch_period_ms > 0 and target_period_ms >= fetch_period_ms:
                    # Calculate the ratio to determine how many 'fetch_timeframe' bars are needed
                    # to cover the duration of 'limit' number of 'timeframe' bars.
                    ratio = target_period_ms // fetch_period_ms
                    # Add a buffer to ensure enough data for accurate resampling and edge cases
                    fetch_limit = limit * ratio + ratio + 200 # +ratio to account for partial bars, +200 for general buffer
                    logger.debug(f"PluginSource: Calculated needed {fetch_timeframe} bars ({fetch_limit}) based on {timeframe} limit ({limit}).")
                elif target_period_ms < fetch_period_ms:
                    logger.warning(
                        f"PluginSource: Requested timeframe '{timeframe}' is smaller than plugin's fetch timeframe '{fetch_timeframe}'. "
                        f"Fetching with original limit {limit} as direct resampling won't work in this direction."
                    )
                    fetch_limit = limit # If somehow fetching a larger TF to resample to a smaller one (unusual for resampling)
                else:
                    logger.warning(f"PluginSource: Fetch timeframe period is zero for '{fetch_timeframe}' or target period is smaller, cannot accurately calculate fetch_limit. Using original limit {limit}.")
                    fetch_limit = limit # Fallback to original limit if period calculation is problematic
            except ValueError as e:
                logger.warning(
                    f"PluginSource: Invalid timeframe string for period calculation ('{timeframe}' or '{fetch_timeframe}'): {e}. "
                    f"Using default fetch_limit = limit."
                )
                fetch_limit = limit # Fallback on parsing errors

        # 7. Calculate `since` timestamp for the initial plugin request if not provided
        # This ensures we fetch enough historical data if 'since' is None (e.g., for 'latest N bars' requests).
        fetch_since = since
        if fetch_since is None:
            try:
                _, _, fetch_period_ms = _parse_timeframe_str(fetch_timeframe)
                if fetch_period_ms > 0:
                    end_time_ms = before if before is not None else int(time.time() * 1000)
                    # Estimate start time by going back `Workspace_limit` bars from `end_time_ms`, plus a buffer.
                    estimated_start_time_ms = end_time_ms - (fetch_limit * fetch_period_ms) - fetch_period_ms # Extra period buffer
                    fetch_since = estimated_start_time_ms
                    logger.debug(f"PluginSource: Estimated fetch_since based on limit and timeframe for {fetch_timeframe}: {fetch_since}ms.")
                else:
                    logger.warning(f"PluginSource: Fetch timeframe period is zero for '{fetch_timeframe}', cannot estimate fetch_since based on limit. Will rely on plugin's default 'since'.")
                    fetch_since = None # Cannot estimate, pass None to plugin
            except ValueError as e:
                logger.warning(f"PluginSource: Invalid fetch timeframe '{fetch_timeframe}' for since calculation: {e}. Skipping estimation, passing None to plugin.", exc_info=True)
                fetch_since = None # Fallback on parsing errors

        logger.info(
            f"PluginSource: Initiating plugin fetch for {self.symbol}. "
            f"Requested TF={timeframe} (limit={limit}), Actual Fetch TF={fetch_timeframe} (limit={fetch_limit}). "
            f"Range=[{fetch_since}ms - {before}ms), ChunkSize={actual_plugin_fetch_limit}."
        )

        # 8. Fetch bars in chunks to handle API limits (e.g., 1000 bars per request)
        all_bars = []
        current_since_for_chunk = fetch_since 
        current_before_for_chunk = before if before is not None else int(time.time() * 1000) # Use the current time if 'before' is not specified

        # Get the period of the fetch_timeframe in milliseconds for calculations
        _, _, fetch_period_ms = _parse_timeframe_str(fetch_timeframe)
        if fetch_period_ms <= 0:
            logger.error(f"PluginSource: Invalid fetch timeframe period ({fetch_timeframe}). Cannot perform chunking. Returning empty list.")
            return []

        remaining_to_fetch_count = fetch_limit # Number of bars still needed for the target timeframe
        while remaining_to_fetch_count > 0:
            # Determine the chunk size for this API call, capped by the plugin's actual limit.
            chunk_size_for_api_call = min(remaining_to_fetch_count, actual_plugin_fetch_limit)
            
            # For fetching new data (since is None), we want to fetch the latest available data up to 'current_before_for_chunk'.
            # If `since` is provided, we fetch forward from `current_since_for_chunk`.
            
            # If original `since` was None, we are implicitly trying to get the latest N bars.
            # In this case, we fetch *backwards* by adjusting the `since` for the API call to cover the chunk.
            api_call_since = None
            api_call_before = None

            if since is None: # Request is for latest N bars (fetch backwards)
                api_call_before = current_before_for_chunk
                # Calculate the start of the current chunk: `chunk_size` bars before `current_before_for_chunk`.
                api_call_since = max(fetch_since, current_before_for_chunk - (chunk_size_for_api_call * fetch_period_ms))
                # Ensure we don't request 'limit' bars from a point in time before the estimated overall 'fetch_since'
                # if fetch_since was calculated.
                
                # If we're at the very beginning of our historical search, adjust limit
                # to only fetch what's left between the (adjusted) api_call_since and api_call_before.
                if api_call_before - api_call_since < fetch_period_ms: # If the interval is too small for even one bar
                    logger.debug(f"PluginSource: Remaining interval too small for another chunk ({api_call_since}-{api_call_before}). Breaking.")
                    break # Stop if no more time range to cover

                # Re-adjust chunk_size_for_api_call based on potentially trimmed range
                chunk_size_for_api_call = max(1, (api_call_before - api_call_since) // fetch_period_ms)
                chunk_size_for_api_call = min(chunk_size_for_api_call, actual_plugin_fetch_limit) # Cap by plugin limit

            else: # Request is for data starting from a specific `since` (fetch forwards)
                api_call_since = current_since_for_chunk
                # Calculate the end of the current chunk: `chunk_size` bars after `current_since_for_chunk`.
                api_call_before = min(current_before_for_chunk, current_since_for_chunk + (chunk_size_for_api_call * fetch_period_ms))
                # Ensure we don't request 'limit' bars from a point in time after the overall 'before'
                # Re-adjust chunk_size_for_api_call based on potentially trimmed range
                chunk_size_for_api_call = max(1, (api_call_before - api_call_since) // fetch_period_ms)
                chunk_size_for_api_call = min(chunk_size_for_api_call, actual_plugin_fetch_limit) # Cap by plugin limit


            if chunk_size_for_api_call <= 0:
                logger.debug(f"PluginSource: Calculated chunk size is 0 or less. Breaking fetching loop for {self.symbol}.")
                break

            logger.debug(f"PluginSource: Fetching chunk of {chunk_size_for_api_call} bars for {self.symbol}/{fetch_timeframe} "
                         f"from {api_call_since}ms to {api_call_before}ms.")
            
            try:
                # Actual call to the plugin's fetch_historical_ohlcv
                bars_chunk = await self.plugin.fetch_historical_ohlcv(
                    provider=self.provider,
                    symbol=self.symbol,
                    timeframe=fetch_timeframe,
                    since=api_call_since,
                    # Pass before to plugin for filtering, but note that CCXT does not typically use 'before'
                    # as a direct parameter in fetch_ohlcv. It would go into 'params'.
                    # We already ensure the time range with 'since' and 'limit'.
                    # For `CryptoPlugin`, the `_with_retries` wraps `Workspace_ohlcv` which expects `since` and `limit`.
                    # For `AlpacaPlugin`, it expects `since` and `limit` as direct arguments, and `before` as `end`.
                    # The `before` for the API call can be passed via `params` if the plugin is designed to pick it up.
                    # For consistency, we pass `before` as part of `params` for `Workspace_historical_ohlcv`.
                    params=None,
                    limit=chunk_size_for_api_call,
                )
                
                if not bars_chunk:
                    logger.debug(f"PluginSource: Plugin returned no more data for {self.symbol}/{fetch_timeframe} in current chunk range. Breaking loop.")
                    break # No more data in this range, stop fetching

                # Filter out any bars outside of the explicitly requested time range
                # (Plugins might return data slightly outside, especially for 'before' which is exclusive).
                # This ensures we strictly adhere to the requested 'before' and 'since' for consistency.
                strict_filtered_chunk = [
                    b for b in bars_chunk
                    if (b.get("timestamp", float('-inf')) >= api_call_since if api_call_since is not None else True) and
                       (b.get("timestamp", float('inf')) < api_call_before if api_call_before is not None else True)
                ]

                # Deduplicate any bars that might already be in all_bars (e.g., from overlapping chunks)
                existing_timestamps = {bar['timestamp'] for bar in all_bars}
                new_unique_bars = [bar for bar in strict_filtered_chunk if bar['timestamp'] not in existing_timestamps]

                if not new_unique_bars:
                    logger.debug(f"PluginSource: Chunk returned {len(bars_chunk)} bars, but no new unique bars found after filtering/deduplication. Assuming end of data for range.")
                    # This could happen if the plugin returns data that's entirely duplicates or out of strict range.
                    if len(all_bars) >= fetch_limit: # If we already have enough from previous chunks, and new ones are duplicates
                        break # Stop if we already satisfied the overall fetch_limit with valid unique bars.
                    # If we don't have enough and got no new, but plugin returned something,
                    # it means there's no more *relevant* unique data in this chunk, so break.
                    break 

                all_bars.extend(new_unique_bars)
                all_bars.sort(key=lambda b: b.get("timestamp", 0)) # Re-sort after extending to maintain order

                # Update remaining_to_fetch_count and `current_since/before_for_chunk` for the next iteration.
                # If fetching latest (since=None), we need to go backwards from the earliest timestamp in the current chunk.
                # If fetching from a specific 'since', we need to go forwards from the latest timestamp in the current chunk.
                
                # If we're fetching from newest to oldest (since is None):
                if since is None: 
                    # The next chunk should end *before* the earliest bar we just received.
                    current_before_for_chunk = new_unique_bars[0]['timestamp'] 
                else: # We are fetching from oldest to newest (since is provided):
                    # The next chunk should start *after* the latest bar we just received.
                    # Add one period to ensure we ask for the *next* bar.
                    current_since_for_chunk = new_unique_bars[-1]['timestamp'] + fetch_period_ms 
                    # If we overshot the original `before` with this chunk, we're done.
                    if current_since_for_chunk >= (before if before is not None else float('inf')):
                         break
                
                # Re-calculate remaining_to_fetch_count based on current length vs. desired length
                remaining_to_fetch_count = max(0, fetch_limit - len(all_bars)) # Only care about unique bars.

                if len(bars_chunk) < chunk_size_for_api_call:
                    logger.debug(f"PluginSource: Plugin returned fewer bars ({len(bars_chunk)}) than requested ({chunk_size_for_api_call}). Assuming end of available data in this direction.")
                    break # Stop if plugin returns less than requested, suggesting no more data from this point.
                
                logger.debug(f"PluginSource: Fetched chunk of {len(bars_chunk)} raw bars ({len(new_unique_bars)} new unique). Total collected: {len(all_bars)}. Remaining to fetch for target: {remaining_to_fetch_count}.")

            except PluginError as e:
                logger.error(f"PluginSource: Plugin fetch failed for {self.symbol}/{fetch_timeframe} during chunking: {e}", exc_info=True)
                raise # Re-raise to be caught by tenacity retry decorator
            except Exception as e:
                logger.error(f"PluginSource: Unexpected error during chunked fetch for {self.symbol}/{fetch_timeframe}: {e}", exc_info=True)
                raise PluginError(f"Unexpected error in fetch_historical_ohlcv during chunking: {e}") from e
        
        if not all_bars:
            logger.info(f"PluginSource: No data fetched for {self.symbol}/{fetch_timeframe} after all attempts and chunks.")
            return []

        # At this point, `all_bars` contains all fetched 1m bars, potentially more than `limit`.
        # The DataOrchestrator's `_apply_filters` will handle the final `since`, `before`, `limit` cropping.
        # But for DB/Cache storage, we only want unique bars within relevant timeframes.

        # 9. Store fetched 1m bars in the database and cache (if 1m)
        # This occurs after data is fetched from the plugin, regardless of resampling needs.
        if fetch_timeframe == "1m": # Only insert/cache if it's the raw 1m data
            try:
                # Use asyncio.create_task for fire-and-forget DB inserts
                asyncio.create_task(
                    insert_ohlcv_to_db(self.market, self.provider, self.symbol, fetch_timeframe, all_bars),
                    name=f"PluginSource_DBInsert_{self.symbol}_1m"
                )
                logger.debug(f"PluginSource: Scheduled DB insert for {len(all_bars)} {fetch_timeframe} bars.")
            except Exception as e:
                logger.warning(f"PluginSource: Failed to schedule DB store for {fetch_timeframe} bars: {e}", exc_info=True)

            if self.cache:
                try:
                    # Store 1m bars in cache (fire-and-forget)
                    asyncio.create_task(
                        self.cache.store_1m_bars(self.market, self.provider, self.symbol, all_bars),
                        name=f"PluginSource_CacheStore_{self.symbol}_1m"
                    )
                    logger.debug(f"PluginSource: Scheduled cache store for {len(all_bars)} {fetch_timeframe} bars.")
                except Exception as e:
                    logger.warning(f"PluginSource: Failed to schedule cache store for {fetch_timeframe} bars: {e}", exc_info=True)

        # 10. Resample if the fetched timeframe is different from the requested timeframe
        if fetch_timeframe != timeframe and all_bars:
            logger.debug(f"PluginSource: Resampling {len(all_bars)} {fetch_timeframe} bars to {timeframe}.")
            resampled_bars = self.resampler.resample(all_bars, timeframe)
            logger.debug(f"PluginSource: Resampling resulted in {len(resampled_bars)} {timeframe} bars.")
            
            # The DataOrchestrator will apply the final filters (since/before/limit)
            # after merging data from all sources. So, we return the resampled data as is.
            return resampled_bars

        # If no resampling needed, return the fetched bars
        logger.debug(f"PluginSource: Returning {len(all_bars)} {timeframe} bars (no resampling needed).")
        logger.info(
            f"PluginSource: Completed fetch_ohlcv for {self.provider}/{self.symbol}/{timeframe}: "
            f"Fetched {len(all_bars)} bars in {time.time() - start_time:.2f}s."
        )
        return all_bars