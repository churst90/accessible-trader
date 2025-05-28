# services/data_orchestrator.py

import asyncio
import logging
import time # For 'now' timestamp if until is None
from typing import Any, Dict, List, Optional

from quart import Config # For type hinting app_config (passed as app_context)
# Import base classes and utilities
from services.data_sources.base import DataSourceError # For raising general orchestrator/source issues
from services.data_sources.cache_source import CacheSource
from services.data_sources.db_source import DbSource
from services.data_sources.aggregate_source import AggregateSource
from services.data_sources.plugin_source import PluginSource
from services.resampler import Resampler
from services.cache_manager import Cache as CacheManagerABC # ABC for the cache manager
from plugins.base import OHLCVBar, MarketPlugin, PluginFeatureNotSupportedError, PluginError
from utils.timeframes import _parse_timeframe_str, format_timestamp_to_iso
from utils.db_utils import DatabaseError # To catch DB errors from sources

# Forward declaration for type hinting MarketService to avoid circular import at module load time
if False: # This block is never executed but helps linters and type checkers
    from services.market_service import MarketService


logger = logging.getLogger(__name__)

# Configuration defaults (can be overridden by app.config)
DEFAULT_ORCHESTRATOR_FETCH_LIMIT = 1000 # Default if limit is None in fetch_ohlcv
DEFAULT_PLUGIN_CHUNK_LIMIT = 500    # Fallback if plugin doesn't specify its own limit
RESAMPLE_FETCH_BUFFER_BARS = 50     # Extra 1m bars to fetch for resampling accuracy
LATEST_N_ESTIMATION_FACTOR = 1.5    # Multiplier for estimating 'since' for "latest N" requests
MAX_PAGING_LOOPS = 200              # Safety break for plugin paging loop

class DataOrchestrator:
    """
    Orchestrates fetching of OHLCV data from various sources:
    1. CacheSource (Redis cache with DB fallback for 1m data, includes resampling)
    2. AggregateSource (TimescaleDB continuous aggregates for non-1m data)
    3. PluginSource (Live data from external exchanges via plugins, with paging)

    It handles data merging (implicitly by order of sources), resampling,
    data storage for newly fetched plugin data, and caching strategies.
    """
    def __init__(self,
                 app_context: Config, # Typically current_app.config
                 market_service: 'MarketService', # Instance of the main MarketService
                 redis_cache_manager: Optional[CacheManagerABC], # Cache manager instance
                 db_source: DbSource, # Shared DbSource instance (primarily for writes)
                 resampler: Resampler  # Shared Resampler instance
                ):
        """
        Initializes the DataOrchestrator.

        Args:
            app_context (Config): The application configuration object.
            market_service (MarketService): Instance of the main MarketService,
                                            used to obtain configured plugin instances.
            redis_cache_manager (Optional[CacheManagerABC]): Instance of the cache manager.
                                                            Can be None if caching is disabled/unavailable.
            db_source (DbSource): Instance of DbSource, used for writing data to the database.
            resampler (Resampler): Instance of Resampler for converting timeframes.
        """
        self.app_config = app_context
        self.market_service = market_service
        self.redis_cache_manager = redis_cache_manager
        self.db_source = db_source # Used for writing 1m data from PluginSource
        self.resampler = resampler
        
        # Load configurable constants
        self.default_orchestrator_limit = int(self.app_config.get("DEFAULT_CHART_POINTS", DEFAULT_ORCHESTRATOR_FETCH_LIMIT))
        self.default_plugin_chunk_limit = int(self.app_config.get("DEFAULT_PLUGIN_CHUNK_SIZE", DEFAULT_PLUGIN_CHUNK_LIMIT))
        self.resample_buffer_bars = int(self.app_config.get("RESAMPLE_FETCH_BUFFER_BARS", RESAMPLE_FETCH_BUFFER_BARS))
        self.latest_n_estimation_factor = float(self.app_config.get("LATEST_N_ESTIMATION_FACTOR", LATEST_N_ESTIMATION_FACTOR))
        self.max_paging_loops = int(self.app_config.get("MAX_PAGING_LOOPS_PLUGIN_FETCH", MAX_PAGING_LOOPS))

        logger.info("DataOrchestrator initialized.")

    async def _fetch_from_plugin_with_paging(
        self,
        plugin_instance: MarketPlugin, # The actual configured plugin instance
        market: str, provider: str, symbol: str,
        timeframe_to_fetch: str, # e.g., "1m" if resampling, or target_timeframe if native
        original_requested_timeframe: str, # The timeframe the user originally asked for
        since: Optional[int], # Overall 'since' for the entire operation
        until: Optional[int], # Overall 'until' for the entire operation
        requested_limit_for_orig_tf: Optional[int], # Limit for the original_requested_timeframe
        params: Optional[Dict[str, Any]], # Passthrough for plugin
        is_backfill: bool # Flag if this is a backfill operation
    ) -> List[OHLCVBar]:
        """
        Fetches data from a plugin, handling pagination if necessary.
        If timeframe_to_fetch is "1m", it saves the fetched 1m bars to DB and 1m Cache.

        Args:
            plugin_instance: The configured MarketPlugin instance to use.
            market, provider, symbol: Identifiers for the data.
            timeframe_to_fetch: The timeframe to request from the plugin (e.g., "1m" or target).
            original_requested_timeframe: The user's original timeframe request.
            since: The overall start timestamp for fetching.
            until: The overall end timestamp for fetching.
            requested_limit_for_orig_tf: The number of bars desired for the original_requested_timeframe.
            params: Additional parameters for the plugin's fetch method.
            is_backfill: True if this is part of a historical backfill process.

        Returns:
            List[OHLCVBar]: A list of fetched (and potentially saved) bars.
        """
        all_fetched_plugin_bars: List[OHLCVBar] = []
        current_fetch_since = since # This is the 'since' for the current chunk we are fetching
        # If fetching latest N bars, 'since' starts as None. We estimate it.
        
        effective_fetch_until = until if until is not None else int(time.time() * 1000) # Fetch up to now if no 'until'

        plugin_max_bars_per_api_call = await plugin_instance.get_fetch_ohlcv_limit()
        if plugin_max_bars_per_api_call <= 0:
            plugin_max_bars_per_api_call = self.default_plugin_chunk_limit
            logger.warning(f"Plugin '{plugin_instance.provider_id}' reported invalid fetch limit. Defaulting to {plugin_max_bars_per_api_call}.")

        # Determine total number of raw bars needed if we know the final limit and are resampling
        total_raw_bars_target: Optional[int] = None
        is_latest_n_bars_request = (since is None and requested_limit_for_orig_tf is not None)

        if requested_limit_for_orig_tf is not None:
            if timeframe_to_fetch == '1m' and original_requested_timeframe != '1m':
                try:
                    _, _, target_tf_ms = _parse_timeframe_str(original_requested_timeframe)
                    _, _, base_tf_ms   = _parse_timeframe_str(timeframe_to_fetch) # Should be 1m
                    if base_tf_ms > 0 and target_tf_ms > base_tf_ms: # Ensure no division by zero and valid hierarchy
                        ratio = target_tf_ms // base_tf_ms
                        if ratio > 0:
                            total_raw_bars_target = (requested_limit_for_orig_tf * ratio) + self.resample_buffer_bars
                except ValueError as e_tf_parse:
                    logger.warning(f"Paging: Error parsing timeframes for 1m total calculation: {e_tf_parse}. Will fetch by range if no limit.")
            else: # Fetching target timeframe natively, or target is 1m.
                total_raw_bars_target = requested_limit_for_orig_tf
        
        # If it's a "latest N bars" request, we need to estimate a `since` to start fetching from.
        if is_latest_n_bars_request and total_raw_bars_target is not None and current_fetch_since is None:
            try:
                _, _, fetch_tf_period_ms = _parse_timeframe_str(timeframe_to_fetch)
                # Estimate how far back we need to go to get total_raw_bars_target
                estimated_duration_ms = int(total_raw_bars_target * fetch_tf_period_ms * self.latest_n_estimation_factor)
                current_fetch_since = effective_fetch_until - estimated_duration_ms
                logger.debug(f"Paging for 'Latest N': Estimated current_fetch_since={current_fetch_since} ({format_timestamp_to_iso(current_fetch_since)}) to fetch ~{total_raw_bars_target} '{timeframe_to_fetch}' bars ending around {format_timestamp_to_iso(effective_fetch_until)}.")
            except ValueError as e_tf_parse:
                logger.warning(f"Paging: Error parsing timeframe '{timeframe_to_fetch}' for 'latest N' since estimation: {e_tf_parse}. `since` remains None.")
                # If current_fetch_since is still None, plugin will fetch latest available up to plugin_max_bars_per_api_call

        log_key_paging = f"{market}:{provider}:{symbol}@{timeframe_to_fetch}"
        logger.debug(f"Paging: Starting for {log_key_paging}. Overall Since: {format_timestamp_to_iso(since)}, Overall Until: {format_timestamp_to_iso(until)}. Target raw bars: {total_raw_bars_target if total_raw_bars_target is not None else 'range-driven'}.")

        # Instantiate PluginSource with the live plugin instance
        plugin_s = PluginSource(
            plugin=plugin_instance,
            market=market,
            provider=provider,
            symbol=symbol
        )

        loop_idx = 0
        while loop_idx < self.max_paging_loops:
            loop_idx += 1

            # Stop if we have a target number of raw bars and we've met or exceeded it
            if total_raw_bars_target is not None and len(all_fetched_plugin_bars) >= total_raw_bars_target:
                logger.debug(f"Paging: Met/exceeded target of {total_raw_bars_target} raw bars for {log_key_paging}. Fetched {len(all_fetched_plugin_bars)}.")
                break

            limit_for_this_api_call = plugin_max_bars_per_api_call
            if total_raw_bars_target is not None:
                remaining_needed = total_raw_bars_target - len(all_fetched_plugin_bars)
                if remaining_needed <= 0: # Should have been caught by previous check
                    break
                limit_for_this_api_call = min(plugin_max_bars_per_api_call, remaining_needed)
            
            if limit_for_this_api_call <= 0: # Safety break
                logger.debug(f"Paging: Calculated limit for API call is {limit_for_this_api_call}. Breaking loop for {log_key_paging}.")
                break
            
            # The 'until' for the plugin call is the overall 'effective_fetch_until'
            # The 'since' for the plugin call is 'current_fetch_since'
            logger.debug(f"Paging ({loop_idx}/{self.max_paging_loops}): Fetching chunk for {log_key_paging}. Since: {format_timestamp_to_iso(current_fetch_since)}, Limit: {limit_for_this_api_call}, Until (context): {format_timestamp_to_iso(effective_fetch_until)}")
            
            # PluginSource.fetch_ohlcv now just calls plugin_instance.fetch_historical_ohlcv
            # We use the plugin_instance directly here for more control over params if needed,
            # or continue using PluginSource if it adds value.
            # For this paging loop, direct plugin call gives more control over 'params' for 'until'.
            chunk_params = params.copy() if params else {}
            # If fetching forward (since is not None), we might need to pass 'until' to the plugin
            # if the plugin supports it and we want to cap the fetch per chunk explicitly.
            # However, CCXT's fetch_ohlcv uses 'since' and 'limit' primarily for forward fetching.
            # For "latest N", current_fetch_since is calculated, and we fetch 'limit' bars from there.
            # Alpaca uses 'start' and 'end'. The plugin wrapper should handle this translation.

            chunk_bars: List[OHLCVBar] = await plugin_instance.fetch_historical_ohlcv(
                symbol=symbol,
                timeframe=timeframe_to_fetch,
                since=current_fetch_since,
                limit=limit_for_this_api_call,
                params=chunk_params # Can include 'until' if plugin supports it.
            )

            if not chunk_bars:
                logger.debug(f"Paging: Plugin returned no data for {log_key_paging} in this chunk (Since: {format_timestamp_to_iso(current_fetch_since)}, Limit: {limit_for_this_api_call}). Total fetched so far: {len(all_fetched_plugin_bars)}.")
                break # No more data from plugin in this direction or range

            all_fetched_plugin_bars.extend(chunk_bars)

            # If we fetched 1m data, asynchronously save it to DB and 1m cache
            if timeframe_to_fetch == '1m' and not is_backfill: # BackfillManager handles its own storage
                dict_chunk_bars = [dict(b) for b in chunk_bars] # Ensure plain dicts
                if self.db_source:
                    asyncio.create_task(self.db_source.store_ohlcv_bars(market, provider, symbol, '1m', dict_chunk_bars), name=f"PagingStoreDB_{log_key_paging}_{loop_idx}")
                if self.redis_cache_manager:
                    asyncio.create_task(self.redis_cache_manager.store_1m_bars(market, provider, symbol, dict_chunk_bars), name=f"PagingStoreCache_{log_key_paging}_{loop_idx}")

            # Determine the 'since' for the next iteration
            # If fetching latest (since was initially None), we fetched backwards from an estimated start.
            # This loop structure primarily assumes fetching forwards from 'since'.
            # For "latest N", this loop might only run once if enough data is fetched.
            # If fetching historical data (since is not None):
            new_since_candidate = chunk_bars[-1]['timestamp'] + 1 # Next bar after the last one fetched

            if current_fetch_since is not None and new_since_candidate <= current_fetch_since:
                logger.warning(f"Paging: No timestamp progress for {log_key_paging}. Last since: {current_fetch_since}, New candidate: {new_since_candidate}. Check plugin for duplicate timestamps or sorting. Breaking.")
                break
            current_fetch_since = new_since_candidate
            
            if current_fetch_since >= effective_fetch_until:
                logger.debug(f"Paging: Reached or passed 'effective_fetch_until' timestamp ({format_timestamp_to_iso(effective_fetch_until)}) for {log_key_paging}.")
                break
            
            # If plugin returns fewer bars than requested, assume it's the end of available data for that range.
            if len(chunk_bars) < limit_for_this_api_call:
                logger.debug(f"Paging: Plugin returned fewer bars ({len(chunk_bars)}) than requested ({limit_for_this_api_call}) for {log_key_paging}. Assuming end of available data in this direction.")
                break
        
        if loop_idx >= self.max_paging_loops:
            logger.warning(f"Paging: Hit max loop count ({self.max_paging_loops}) for {log_key_paging}. Fetched {len(all_fetched_plugin_bars)} bars.")

        logger.info(f"Paging: Completed for {log_key_paging}. Total raw bars fetched via plugin: {len(all_fetched_plugin_bars)}.")
        return all_fetched_plugin_bars

    async def _apply_filters(
        self,
        bars: List[OHLCVBar],
        since_ms: Optional[int],
        until_ms: Optional[int], # Changed from before_ms for clarity with 'until' parameter
        target_bars_limit: int,
        log_key_context: str
    ) -> List[OHLCVBar]:
        """
        Applies final time range (since, until) and limit filters to a list of bars.
        Assumes bars are already sorted chronologically (oldest first).
        """
        if not bars:
            return []

        filtered_bars = bars
        original_count = len(filtered_bars)

        # Apply 'since' filter (inclusive)
        if since_ms is not None:
            filtered_bars = [b for b in filtered_bars if b['timestamp'] >= since_ms]
        
        # Apply 'until' filter (exclusive)
        if until_ms is not None:
            filtered_bars = [b for b in filtered_bars if b['timestamp'] < until_ms]
        
        count_after_time_filter = len(filtered_bars)

        # Apply limit
        if len(filtered_bars) > target_bars_limit:
            if since_ms is None and until_ms is not None: # Fetching latest N bars ending at 'until_ms'
                filtered_bars = filtered_bars[-target_bars_limit:]
            elif since_ms is None and until_ms is None: # Fetching latest N bars ending now
                filtered_bars = filtered_bars[-target_bars_limit:]
            else: # Fetching from a specific 'since_ms', take the first N bars
                filtered_bars = filtered_bars[:target_bars_limit]
        
        logger.debug(
            f"DataOrchestrator ({log_key_context}): _apply_filters: "
            f"Original: {original_count}, After time filter ({format_timestamp_to_iso(since_ms)}-{format_timestamp_to_iso(until_ms)}): {count_after_time_filter}, "
            f"After limit ({target_bars_limit}): {len(filtered_bars)} bars."
        )
        return filtered_bars

    async def fetch_ohlcv(
        self, market: str, provider: str, symbol: str, requested_timeframe: str,
        since: Optional[int] = None, limit: Optional[int] = None,
        until: Optional[int] = None, 
        params: Optional[Dict[str, Any]] = None, # For plugin passthrough
        user_id_for_plugin: Optional[str] = None, # For getting correct plugin instance
        use_cache_source: bool = True, # Allow disabling CacheSource (includes DB reads for 1m)
        use_aggregates: bool = True,   # Allow disabling AggregateSource
        use_plugin_source: bool = True,    # Allow disabling PluginSource
        is_backfill: bool = False      # To inform sources if it's a backfill op
    ) -> List[OHLCVBar]:
        """
        Fetches OHLCV data by trying different sources in order: Cache, Aggregates, Plugin.
        Handles resampling if 1m data is fetched for a higher timeframe.
        Saves newly fetched 1m plugin data to DB and Cache.
        Saves resampled data from plugins to Cache.
        """
        log_key = f"{market}:{provider}:{symbol}@{requested_timeframe}"
        start_time_orchestration = time.monotonic()
        logger.debug(f"DataOrchestrator: Fetching OHLCV for {log_key}. Since={format_timestamp_to_iso(since)}, Until={format_timestamp_to_iso(until)}, Limit={limit}, User={user_id_for_plugin}")

        final_bars: List[OHLCVBar] = []
        source_used_description = "NoSourceAttempted"
        
        # Determine the actual limit for queries
        query_limit = limit if limit is not None else self.default_orchestrator_limit
        if query_limit <= 0: query_limit = self.default_orchestrator_limit # Ensure positive limit

        # 1. Try CacheSource (handles 1m from Redis/DB, and resampled from Redis)
        if use_cache_source and self.redis_cache_manager and self.resampler:
            logger.debug(f"DataOrchestrator: Attempting CacheSource for {log_key}.")
            cache_s = CacheSource(market, provider, symbol, self.redis_cache_manager, self.resampler)
            try:
                # CacheSource expects 'before' which corresponds to our 'until'
                cache_bars_dicts = await cache_s.fetch_ohlcv(requested_timeframe, since, before=until, limit=query_limit)
                if cache_bars_dicts:
                    final_bars = [OHLCVBar(**bar) for bar in cache_bars_dicts] # Convert dicts to OHLCVBar
                    source_used_description = "CacheSource (Redis or DB+Resample)"
                    logger.info(f"DataOrchestrator: {len(final_bars)} bars from {source_used_description} for {log_key}.")
            except Exception as e_cs:
                logger.warning(f"DataOrchestrator: CacheSource failed for {log_key}: {e_cs}", exc_info=True)
                final_bars = [] # Ensure final_bars is empty if source fails

        # 2. If CacheSource missed AND non-1m timeframe, try AggregateSource (TimescaleDB aggregates)
        if not final_bars and use_aggregates and requested_timeframe != '1m':
            logger.debug(f"DataOrchestrator: CacheSource miss/disabled, attempting AggregateSource for non-1m {log_key}.")
            aggregate_s = AggregateSource(market=market, provider=provider, symbol=symbol)
            try:
                # AggregateSource also expects 'before' (our 'until') and int 'limit'
                agg_bars_dicts = await aggregate_s.fetch_ohlcv(requested_timeframe, since, before=until, limit=query_limit)
                if agg_bars_dicts:
                    final_bars = [OHLCVBar(**bar) for bar in agg_bars_dicts]
                    source_used_description = "AggregateSource (TimescaleDB)"
                    logger.info(f"DataOrchestrator: Fetched {len(final_bars)} bars from {source_used_description} for {log_key}.")
                    # If aggregates provided data, cache it as "resampled" data
                    if final_bars and self.redis_cache_manager:
                        resampled_cache_key = f"ohlcv:{market}:{provider}:{symbol}:{requested_timeframe}"
                        ttl_resampled = getattr(self.redis_cache_manager, 'ttl_resampled', 300)
                        asyncio.create_task(
                            self.redis_cache_manager.set_resampled(resampled_cache_key, [dict(b) for b in final_bars], ttl_resampled),
                            name=f"StoreAggToCache_{log_key}"
                        )
            except DatabaseError as e_agg_db:
                 logger.error(f"DataOrchestrator: AggregateSource DB error for {log_key}: {e_agg_db}", exc_info=True)
            except Exception as e_agg:
                 logger.error(f"DataOrchestrator: AggregateSource failed for {log_key}: {e_agg}", exc_info=True)
                 final_bars = []


        # 3. If all prior sources missed or were disabled, try PluginSource (live from exchange)
        if not final_bars and use_plugin_source:
            logger.debug(f"DataOrchestrator: Prior sources missed/disabled for {log_key}. Attempting PluginSource.")
            plugin_instance = await self.market_service.get_plugin_instance(
                market, provider, user_id=user_id_for_plugin
            )
            if not plugin_instance:
                logger.warning(f"DataOrchestrator: Could not get plugin instance for {market}:{provider}. Cannot use PluginSource.")
                # Fall through, might return empty if no other source provided data
            else:
                timeframe_to_fetch_from_plugin = requested_timeframe
                resample_after_plugin_fetch = False

                # If target is not 1m, we fetch 1m from plugin and then resample.
                if requested_timeframe != '1m':
                    # Check if plugin natively supports the target timeframe
                    plugin_supported_tfs = await plugin_instance.get_supported_timeframes() or []
                    if requested_timeframe not in plugin_supported_tfs:
                        logger.info(f"DataOrchestrator: Plugin '{plugin_instance.provider_id}' does not natively support '{requested_timeframe}'. Will fetch '1m' and resample for {log_key}.")
                        timeframe_to_fetch_from_plugin = '1m'
                        resample_after_plugin_fetch = True
                    else:
                        logger.info(f"DataOrchestrator: Plugin '{plugin_instance.provider_id}' natively supports '{requested_timeframe}'. Will fetch directly for {log_key}.")
                        # timeframe_to_fetch_from_plugin remains requested_timeframe
                
                logger.debug(f"DataOrchestrator: Will fetch '{timeframe_to_fetch_from_plugin}' from plugin for {log_key}. Resample needed: {resample_after_plugin_fetch}.")
                try:
                    # _fetch_from_plugin_with_paging handles fetching and saving 1m data
                    raw_plugin_bars = await self._fetch_from_plugin_with_paging(
                        plugin_instance, market, provider, symbol,
                        timeframe_to_fetch_from_plugin, requested_timeframe,
                        since, until, query_limit, # Pass query_limit as requested_limit_for_orig_tf
                        params, is_backfill
                    )
                    source_used_description = f"PluginSource ({plugin_instance.provider_id})"

                    if raw_plugin_bars:
                        if resample_after_plugin_fetch and self.resampler:
                            logger.debug(f"DataOrchestrator: Resampling {len(raw_plugin_bars)} '{timeframe_to_fetch_from_plugin}' bars to '{requested_timeframe}' for {log_key}.")
                            # Note: resampler.resample doesn't currently take a limit argument in its signature.
                            # The limiting should be done after resampling or by fetching an appropriate number of 1m bars.
                            # The `_apply_filters` method will handle the final limit.
                            final_bars = self.resampler.resample(raw_plugin_bars, requested_timeframe) # Pass original list of dicts
                            logger.info(f"DataOrchestrator: Resampled to {len(final_bars)} '{requested_timeframe}' bars for {log_key}.")
                            # Cache the resampled data
                            if final_bars and self.redis_cache_manager:
                                resampled_cache_key = f"ohlcv:{market}:{provider}:{symbol}:{requested_timeframe}"
                                ttl_resampled = getattr(self.redis_cache_manager, 'ttl_resampled', 300)
                                asyncio.create_task(
                                    self.redis_cache_manager.set_resampled(resampled_cache_key, [dict(b) for b in final_bars], ttl_resampled),
                                    name=f"StoreResampledPluginToCache_{log_key}"
                                )
                        else: # Natively fetched target timeframe from plugin, or 1m data
                            final_bars = raw_plugin_bars
                            # If it was a native non-1m fetch, cache it as "resampled"
                            if timeframe_to_fetch_from_plugin != '1m' and final_bars and self.redis_cache_manager:
                                native_cache_key = f"ohlcv:{market}:{provider}:{symbol}:{timeframe_to_fetch_from_plugin}"
                                ttl_native = getattr(self.redis_cache_manager, 'ttl_resampled', 300) # Use same TTL
                                asyncio.create_task(
                                    self.redis_cache_manager.set_resampled(native_cache_key, [dict(b) for b in final_bars], ttl_native),
                                    name=f"StoreNativePluginToCache_{log_key}"
                                )
                    else: # No bars from plugin
                        final_bars = []
                except PluginFeatureNotSupportedError as e_pfnse:
                     logger.warning(f"DataOrchestrator: PluginSource failed for {log_key} as feature not supported: {e_pfnse}")
                     final_bars = [] # Ensure it's empty
                except DataSourceError as e_dse: # Catch errors from PluginSource itself
                    logger.error(f"DataOrchestrator: PluginSource fetch failed for {log_key}: {e_dse}", exc_info=True)
                    final_bars = []
                except Exception as e_plugin_generic:
                    logger.error(f"DataOrchestrator: Unexpected error during PluginSource fetch for {log_key}: {e_plugin_generic}", exc_info=True)
                    final_bars = []

        # 4. Final common processing: sort and apply limit after all sources.
        # Bars from individual sources should ideally be sorted, but merge & final sort ensures.
        if final_bars:
            # Deduplicate by timestamp, keeping the last seen (though with ordered sources, less likely an issue)
            # Using a dict for deduplication by timestamp
            unique_bars_map: Dict[int, OHLCVBar] = {bar['timestamp']: bar for bar in final_bars}
            if len(unique_bars_map) < len(final_bars):
                logger.debug(f"DataOrchestrator: Deduplicated {len(final_bars) - len(unique_bars_map)} bars for {log_key}.")
            
            sorted_bars = sorted(unique_bars_map.values(), key=lambda b: b['timestamp'])
            
            # Apply the final precise since, until, and limit filtering
            # The 'until' here is the original 'until' passed to fetch_ohlcv
            final_bars = await self._apply_filters(sorted_bars, since, until, query_limit, log_key)
        
        duration_orchestration = time.monotonic() - start_time_orchestration
        logger.info(
            f"DataOrchestrator: Request for {log_key} completed in {duration_orchestration:.3f}s. "
            f"Source: {source_used_description if final_bars else 'None/Failed'}. "
            f"Returned: {len(final_bars)} bars."
        )
        return final_bars

    async def close(self):
        """Perform any cleanup for DataOrchestrator if needed."""
        logger.info("DataOrchestrator closing (if any specific cleanup were needed).")
        # Currently, DataOrchestrator doesn't hold long-lived resources itself that need explicit closing.
        # Its dependencies (MarketService, CacheManager, etc.) are managed externally.
        pass