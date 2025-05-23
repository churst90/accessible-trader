# services/backfill_manager.py

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

from quart import current_app # For accessing app.config
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type, RetryError
from prometheus_client import Counter, Gauge # Assuming REGISTRY check is handled globally or not needed here

from plugins.base import MarketPlugin, PluginError, OHLCVBar, NetworkPluginError # Import OHLCVBar TypedDict
from utils.db_utils import DatabaseError, fetch_query, insert_ohlcv_to_db, has_data_in_range
from utils.timeframes import UNIT_MS, format_timestamp_to_iso # For period_ms calculation & logging
# Removed: _parse_timeframe_str as backfill always deals with '1m' internally for UNIT_MS['m']

# Import CacheManagerABC for type hinting, though direct interaction might be through an instance
from services.cache_manager import Cache as CacheManagerABC

logger = logging.getLogger(__name__)

# Global dictionaries for managing active backfill tasks and their locks.
# Keyed by Tuple[str, str, str]: (market, provider, symbol)
_backfill_tasks: Dict[Tuple[str, str, str], asyncio.Task] = {}
_backfill_locks: Dict[Tuple[str, str, str], asyncio.Lock] = {}

# Prometheus metrics
# These would ideally be accessed from a central metrics registry configured at app startup
# to avoid issues with re-registration upon module reload during development.
# For example, they could be attributes of `current_app.prom_metrics` if set up that way.
BACKFILL_CHUNKS_METRIC = getattr(current_app, "prom_metrics_backfill_chunks", None) if current_app else None
BACKFILL_GAP_METRIC = getattr(current_app, "prom_metrics_backfill_gap", None) if current_app else None


class BackfillManager:
    """
    Manages historical data backfills for 1-minute OHLCV bars for a specific asset.

    This class is responsible for:
    - Detecting if a data gap exists in the database for 1-minute data.
    - Triggering and managing background asyncio Tasks to fetch missing historical
      data from a provided `MarketPlugin` instance in manageable chunks.
    - Storing the fetched 1-minute data into the database and the 1m cache.
    - Using asyncio locks to prevent concurrent backfill operations for the same asset.
    - Implementing retry mechanisms for transient errors during data fetching.
    - Respecting API limits and efficiently querying for missing data ranges.

    An instance of BackfillManager is typically created for a specific market, provider,
    and symbol, and is provided with a pre-configured plugin instance.
    """

    _global_api_semaphore: Optional[asyncio.Semaphore] = None # Class-level semaphore

    def __init__(
        self,
        market: str,
        provider: str,
        symbol: str,
        plugin: MarketPlugin, # Expects an already instantiated and configured plugin
        cache: Optional[CacheManagerABC], # Shared CacheManager instance
    ):
        """
        Initializes the BackfillManager for a specific asset and plugin.

        Args:
            market (str): The market identifier (e.g., 'crypto', 'stocks').
            provider (str): The data provider identifier (e.g., 'binance', 'alpaca').
                            This must match the provider_id the plugin instance is configured for.
            symbol (str): The trading symbol (e.g., 'BTC/USDT', 'AAPL').
            plugin (MarketPlugin): An instantiated `MarketPlugin` object, ready to be used
                                   for fetching data for the specified provider.
            cache (Optional[CacheManagerABC]): Cache manager instance for storing fetched 1m data.
                                             Can be None if caching is not available/desired.

        Raises:
            ValueError: If market, provider, symbol, or plugin are invalid,
                        or if critical configuration values are missing or invalid.
        """
        if not all([market, provider, symbol]):
            raise ValueError("BackfillManager: market, provider, and symbol must be non-empty strings.")
        if not isinstance(plugin, MarketPlugin):
            raise ValueError("BackfillManager: plugin must be an instance of MarketPlugin.")
        if provider.lower() != plugin.provider_id.lower():
            # Ensure the BackfillManager's provider context matches the plugin's configured provider_id
            raise ValueError(
                f"BackfillManager provider '{provider}' does not match "
                f"plugin's configured provider_id '{plugin.provider_id}'."
            )

        self.market: str = market
        self.provider: str = provider # Matches plugin.provider_id
        self.symbol: str = symbol
        self.plugin: MarketPlugin = plugin
        self.cache: Optional[CacheManagerABC] = cache
        self.asset_key: Tuple[str, str, str] = (self.market, self.provider, self.symbol)

        # Load configurations from current_app.config
        cfg = current_app.config
        try:
            self.default_plugin_fetch_limit_1m: int = int(cfg.get("DEFAULT_PLUGIN_CHUNK_SIZE", 500))
            self.max_chunks_per_run: int = int(cfg.get("MAX_BACKFILL_CHUNKS_PER_RUN", 100))
            self.chunk_fetch_delay_s: float = float(cfg.get("BACKFILL_CHUNK_DELAY_SEC", 1.5))
            self.default_lookback_period_ms: int = int(cfg.get("DEFAULT_BACKFILL_PERIOD_MS", 30 * 24 * 60 * 60 * 1000)) # 30 days

            if BackfillManager._global_api_semaphore is None:
                 BackfillManager._global_api_semaphore = asyncio.Semaphore(
                    int(cfg.get("BACKFILL_API_CONCURRENCY", 5))
                 )
            self._api_semaphore: asyncio.Semaphore = BackfillManager._global_api_semaphore
            
        except (ValueError, TypeError) as ve_cfg:
            logger.critical(f"BackfillManager ({self.asset_key}): Invalid configuration value: {ve_cfg}", exc_info=True)
            raise ValueError(f"Configuration error for BackfillManager: {ve_cfg}") from ve_cfg
        except Exception as e_cfg_unexpected:
            logger.critical(f"BackfillManager ({self.asset_key}): Unexpected error loading configuration: {e_cfg_unexpected}", exc_info=True)
            raise RuntimeError(f"BackfillManager init failed due to config error: {e_cfg_unexpected}") from e_cfg_unexpected

        logger.debug(f"BackfillManager initialized for {self.asset_key}.")

    async def find_missing_1m_ranges(self, overall_since_ms: int, overall_until_ms: int) -> List[Tuple[int, int]]:
        """
        Identifies time ranges where 1-minute OHLCV data is missing in the database
        for the manager's configured asset, within a given overall period.
        """
        log_prefix = f"FindMissingRanges ({self.asset_key}):"
        # ... (rest of the method as provided previously) ...
        logger.debug(f"{log_prefix} Checking for 1m gaps between {format_timestamp_to_iso(overall_since_ms)} and {format_timestamp_to_iso(overall_until_ms)}.")
        effective_since_ms = max(0, overall_since_ms)
        if effective_since_ms >= overall_until_ms:
            logger.debug(f"{log_prefix} Invalid range: since ({effective_since_ms}) >= until ({overall_until_ms}). No gaps possible.")
            return []
        one_minute_ms = UNIT_MS['m']
        query = """
            SELECT timestamp FROM ohlcv_data
            WHERE market = $1 AND provider = $2 AND symbol = $3 AND timeframe = '1m'
              AND timestamp >= $4 AND timestamp < $5
            ORDER BY timestamp ASC
        """
        since_dt = datetime.fromtimestamp(effective_since_ms / 1000.0, tz=timezone.utc)
        until_dt = datetime.fromtimestamp(overall_until_ms / 1000.0, tz=timezone.utc)
        try:
            db_records = await fetch_query(query, self.market, self.provider, self.symbol, since_dt, until_dt)
        except DatabaseError as e_db:
            logger.error(f"{log_prefix} DatabaseError querying existing 1m timestamps: {e_db}", exc_info=True)
            return []
        missing_ranges: List[Tuple[int, int]] = []
        current_expected_ts_ms = effective_since_ms
        for record in db_records:
            bar_ts_ms = int(record["timestamp"].timestamp() * 1000)
            if bar_ts_ms > current_expected_ts_ms:
                missing_ranges.append((current_expected_ts_ms, bar_ts_ms))
            current_expected_ts_ms = bar_ts_ms + one_minute_ms
        if current_expected_ts_ms < overall_until_ms:
            missing_ranges.append((current_expected_ts_ms, overall_until_ms))
        if missing_ranges:
            logger.info(f"{log_prefix} Found {len(missing_ranges)} missing 1m data ranges.")
            for start_gap, end_gap in missing_ranges[:3]:
                 logger.debug(f"{log_prefix} Gap: {format_timestamp_to_iso(start_gap)} to {format_timestamp_to_iso(end_gap)}")
        else:
            logger.debug(f"{log_prefix} No missing 1m data ranges found in the specified period.")
        return sorted(missing_ranges)


    async def trigger_historical_backfill_if_needed(self, timeframe_context: Optional[str] = None) -> None:
        """
        Checks if a historical data gap exists and triggers a background backfill task.
        """
        log_prefix = f"BackfillTrigger ({self.asset_key}, ContextTF: {timeframe_context or 'N/A'}):"
        # ... (rest of the method as provided previously) ...
        active_task = _backfill_tasks.get(self.asset_key)
        if active_task and not active_task.done():
            logger.debug(f"{log_prefix} Backfill task is already running. Skipping new trigger.")
            return
        now_ms = int(time.time() * 1000)
        target_oldest_ms_for_gap_check = now_ms - self.default_lookback_period_ms
        logger.debug(f"{log_prefix} Checking for backfill need. Target oldest data: {format_timestamp_to_iso(target_oldest_ms_for_gap_check)}.")
        try:
            gap_is_present = await self._is_historical_data_gap_present(target_oldest_ms_for_gap_check, now_ms)
            if not gap_is_present:
                logger.debug(f"{log_prefix} No significant historical data gap found. No backfill needed at this time.")
                if BACKFILL_GAP_METRIC: BACKFILL_GAP_METRIC.labels(market=self.market, provider=self.provider, symbol=self.symbol).set(0)
                return
            lock = _backfill_locks.setdefault(self.asset_key, asyncio.Lock())
            if lock.locked():
                logger.debug(f"{log_prefix} Backfill lock is already held by another coroutine. Skipping trigger.")
                return
            async with lock:
                if _backfill_tasks.get(self.asset_key) and not _backfill_tasks[self.asset_key].done():
                    logger.debug(f"{log_prefix} Backfill was started by another coroutine while waiting for lock. Skipping.")
                    return
                logger.info(f"{log_prefix} Historical data gap detected. Starting background backfill task to cover up to {format_timestamp_to_iso(target_oldest_ms_for_gap_check)}.")
                task_name = f"BackfillRun_{self.market}_{self.provider}_{self.symbol}"
                _backfill_tasks[self.asset_key] = asyncio.create_task(
                    self._run_historical_backfill(target_oldest_ms_for_gap_check, now_ms), name=task_name
                )
        except Exception as e_trigger:
            logger.error(f"{log_prefix} Error during backfill trigger process: {e_trigger}", exc_info=True)


    async def _is_historical_data_gap_present(self, target_oldest_ms: int, current_time_ms: int) -> bool:
        """
        Checks if a data gap exists by comparing the earliest existing 1m database timestamp
        against the `target_oldest_ms`.
        """
        log_prefix = f"GapCheck ({self.asset_key}):"
        # ... (rest of the method as provided previously) ...
        logger.debug(f"{log_prefix} Target oldest for gap check: {format_timestamp_to_iso(target_oldest_ms)}.")
        try:
            if target_oldest_ms >= current_time_ms:
                 logger.warning(f"{log_prefix} Target oldest {target_oldest_ms} is not before current time {current_time_ms}. Assuming no gap by this logic.")
                 return False
            data_exists_in_target_period = await has_data_in_range(
                self.market, self.provider, self.symbol, "1m",
                target_oldest_ms,
                current_time_ms
            )
            if not data_exists_in_target_period:
                logger.info(f"{log_prefix} No 1m data found at all between {format_timestamp_to_iso(target_oldest_ms)} and {format_timestamp_to_iso(current_time_ms)}. Gap detected.")
                if BACKFILL_GAP_METRIC: BACKFILL_GAP_METRIC.labels(market=self.market, provider=self.provider, symbol=self.symbol).set(current_time_ms - target_oldest_ms)
                return True
            rows = await fetch_query(
                "SELECT MIN(timestamp) AS min_ts FROM ohlcv_data "
                "WHERE market=$1 AND provider=$2 AND symbol=$3 AND timeframe='1m'",
                self.market, self.provider, self.symbol
            )
            if rows and rows[0] and rows[0]['min_ts'] is not None:
                earliest_db_ts_dt = rows[0]['min_ts']
                if isinstance(earliest_db_ts_dt, datetime):
                    earliest_db_ts_ms = int(earliest_db_ts_dt.timestamp() * 1000)
                    logger.debug(f"{log_prefix} Earliest 1m data in DB for {self.symbol}: {format_timestamp_to_iso(earliest_db_ts_ms)}.")
                    buffer_ms = 5 * UNIT_MS['m'] 
                    gap_detected = earliest_db_ts_ms > (target_oldest_ms + buffer_ms)
                    if BACKFILL_GAP_METRIC: BACKFILL_GAP_METRIC.labels(market=self.market, provider=self.provider, symbol=self.symbol).set(earliest_db_ts_ms - target_oldest_ms if gap_detected else 0)
                    if gap_detected:
                        logger.info(f"{log_prefix} Gap detected. Earliest DB data ({format_timestamp_to_iso(earliest_db_ts_ms)}) is after target ({format_timestamp_to_iso(target_oldest_ms)} + buffer).")
                    return gap_detected
                else:
                    logger.warning(f"{log_prefix} Unexpected type for min_ts: {type(earliest_db_ts_dt)}. Assuming gap.")
                    return True
            else:
                logger.info(f"{log_prefix} No 1m data found at all in DB for {self.symbol}. Full historical gap.")
                if BACKFILL_GAP_METRIC: BACKFILL_GAP_METRIC.labels(market=self.market, provider=self.provider, symbol=self.symbol).set(current_time_ms - target_oldest_ms)
                return True
        except DatabaseError as dbe:
            logger.error(f"{log_prefix} DB error during gap check: {dbe}", exc_info=True)
            return False
        except Exception as e_check:
            logger.error(f"{log_prefix} Unexpected error during gap check: {e_check}", exc_info=True)
            return False
        return False

    async def _run_historical_backfill(self, overall_target_oldest_ms: int, current_time_ms: int) -> None:
        """
        Performs the historical data backfill for `self.symbol`.
        """
        log_prefix = f"RunBackfill ({self.asset_key}):"
        logger.info(f"{log_prefix} Starting backfill run. Overall target oldest: {format_timestamp_to_iso(overall_target_oldest_ms)}.")

        try:
            all_identified_gaps = await self.find_missing_1m_ranges(overall_target_oldest_ms, current_time_ms)
            all_identified_gaps.sort(key=lambda r: r[0], reverse=True) 

            if not all_identified_gaps:
                logger.info(f"{log_prefix} No missing 1m ranges found. Backfill complete or unnecessary.")
                return

            plugin_1m_fetch_limit = await self.plugin.get_fetch_ohlcv_limit()
            if plugin_1m_fetch_limit <= 0 : plugin_1m_fetch_limit = self.default_plugin_fetch_limit_1m

            total_chunks_this_run = 0
            total_bars_inserted_this_run = 0
            one_minute_ms = UNIT_MS['m']

            for gap_start_ms, gap_end_ms in all_identified_gaps:
                if total_chunks_this_run >= self.max_chunks_per_run:
                    logger.info(f"{log_prefix} Reached max_chunks_per_run. Will continue later if gaps remain.")
                    break
                
                logger.info(f"{log_prefix} Processing gap: {format_timestamp_to_iso(gap_start_ms)} to {format_timestamp_to_iso(gap_end_ms)}.")
                current_chunk_effective_until_ms = gap_end_ms

                while current_chunk_effective_until_ms > gap_start_ms and total_chunks_this_run < self.max_chunks_per_run:
                    chunk_fetch_since_ms = current_chunk_effective_until_ms - (plugin_1m_fetch_limit * one_minute_ms)
                    chunk_fetch_since_ms = max(chunk_fetch_since_ms, gap_start_ms, overall_target_oldest_ms)
                    
                    if chunk_fetch_since_ms >= current_chunk_effective_until_ms:
                        break 
                    
                    num_bars_in_chunk_range = (current_chunk_effective_until_ms - chunk_fetch_since_ms) // one_minute_ms
                    limit_for_api_call = min(plugin_1m_fetch_limit, max(1, num_bars_in_chunk_range))

                    if limit_for_api_call == 0: break

                    params_for_plugin = {'until_ms': current_chunk_effective_until_ms} 

                    fetched_bars_in_chunk: List[OHLCVBar] = []
                    async with self._api_semaphore:
                        try: # REMOVED THE EXTRA { HERE
                            fetched_bars_in_chunk = await self._process_backfill_chunk(
                                chunk_num_idx=total_chunks_this_run,
                                since_ms_for_plugin=chunk_fetch_since_ms,
                                limit_for_plugin=limit_for_api_call,
                                params_for_plugin=params_for_plugin
                            )
                        except RetryError as e_retry: 
                            logger.error(f"{log_prefix} Chunk fetch failed after all retries for range ending {format_timestamp_to_iso(current_chunk_effective_until_ms)}: {e_retry}", exc_info=True)
                            break 
                        except PluginError as e_plugin: 
                            logger.error(f"{log_prefix} Non-retriable PluginError processing chunk for range ending {format_timestamp_to_iso(current_chunk_effective_until_ms)}: {e_plugin}", exc_info=True)
                            break
                        except Exception as e_chunk_proc:
                             logger.error(f"{log_prefix} Unexpected error in _process_backfill_chunk: {e_chunk_proc}", exc_info=True)
                             break
                    
                    total_chunks_this_run += 1
                    if fetched_bars_in_chunk:
                        total_bars_inserted_this_run += len(fetched_bars_in_chunk)
                        current_chunk_effective_until_ms = fetched_bars_in_chunk[0]['timestamp'] 
                    else: 
                        logger.debug(f"{log_prefix} Chunk yielded no new older bars for range ending {format_timestamp_to_iso(current_chunk_effective_until_ms)}. Assuming end of data for this segment.")
                        break 
                    
                    await asyncio.sleep(self.chunk_fetch_delay_s)

            logger.info(f"{log_prefix} Backfill run segment finished. Total chunks: {total_chunks_this_run}. Total bars inserted: {total_bars_inserted_this_run}.")

        except asyncio.CancelledError:
            logger.info(f"{log_prefix} Backfill task was cancelled.")
            raise
        except Exception as e_run_main:
            logger.error(f"{log_prefix} Critical unhandled error in backfill process: {e_run_main}", exc_info=True)
        finally:
            _backfill_tasks.pop(self.asset_key, None)
            lock = _backfill_locks.get(self.asset_key)
            if lock and lock.locked():
                try:
                    lock.release()
                    logger.debug(f"{log_prefix} Lock released.")
                except RuntimeError: 
                    logger.warning(f"{log_prefix} Attempted to release an already unlocked lock.")
            logger.info(f"{log_prefix} Backfill task fully cleaned up.")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2), 
        retry=retry_if_exception_type(NetworkPluginError),
        after=lambda retry_state: logger.warning(
            f"BackfillChunk ({getattr(retry_state.args[0], 'asset_key', 'UnknownAsset')} "  # Access self via args[0]
            f"Attempt {retry_state.attempt_number}/{retry_state.attempt_number + retry_state.retry_object.stop.max_attempt_number -1}): "
            f"Failed due to {type(retry_state.outcome.exception()).__name__}. "
            f"Next attempt in {retry_state.next_wait_time:.2f}s." if retry_state.next_wait_time is not None else "No more retries."
        ),
        reraise=True
    )
    async def _process_backfill_chunk(
        self,
        chunk_num_idx: int, 
        since_ms_for_plugin: int,
        limit_for_plugin: int,
        params_for_plugin: Optional[Dict[str, Any]] = None
    ) -> List[OHLCVBar]:
        """
        Processes a single chunk of historical 1m data for backfill.
        """
        log_prefix = f"ProcessChunk ({self.asset_key}, Chunk {chunk_num_idx + 1}):"
        # ... (rest of the method as provided previously, ensure format_timestamp_to_iso is imported/available) ...
        logger.debug(
            f"{log_prefix} Fetching 1m bars. Since: {format_timestamp_to_iso(since_ms_for_plugin)}, "
            f"Limit: {limit_for_plugin}, Params: {params_for_plugin}."
        )
        bars_from_plugin: List[OHLCVBar] = await self.plugin.fetch_historical_ohlcv(
            symbol=self.symbol,
            timeframe="1m",
            since=since_ms_for_plugin,
            limit=limit_for_plugin,
            params=params_for_plugin
        )
        if not bars_from_plugin:
            logger.info(f"{log_prefix} Plugin returned no data for the requested range.")
            return []
        bars_from_plugin.sort(key=lambda b: b['timestamp'])
        newly_fetched_bars = bars_from_plugin
        if not newly_fetched_bars:
            logger.info(f"{log_prefix} No new relevant older bars after filtering (Plugin returned {len(bars_from_plugin)} total).")
            return []
        dict_bars_to_store = [dict(b) for b in newly_fetched_bars]
        try:
            asyncio.create_task(
                insert_ohlcv_to_db(self.market, self.provider, self.symbol, "1m", dict_bars_to_store),
                name=f"BackfillDBInsert_{self.symbol}_Chunk{chunk_num_idx}"
            )
            logger.debug(f"{log_prefix} DB insert task created for {len(newly_fetched_bars)} bars.")
            if self.cache and hasattr(self.cache, 'store_1m_bars'):
                asyncio.create_task(
                    self.cache.store_1m_bars(self.market, self.provider, self.symbol, dict_bars_to_store),
                    name=f"BackfillCacheStore_{self.symbol}_Chunk{chunk_num_idx}"
                )
                logger.debug(f"{log_prefix} 1m Cache store task created for {len(newly_fetched_bars)} bars.")
        except DatabaseError as dbe_insert:
            logger.error(f"{log_prefix} DB error during scheduling insert for {len(newly_fetched_bars)} bars: {dbe_insert}", exc_info=True)
            raise 
        except Exception as e_store_task: 
            logger.error(f"{log_prefix} Error scheduling storage tasks for {len(newly_fetched_bars)} bars: {e_store_task}", exc_info=True)
            raise PluginError(message=f"Failed to schedule storage tasks: {e_store_task}", provider_id=self.provider, original_exception=e_store_task) from e_store_task
        if BACKFILL_CHUNKS_METRIC: # Check if metric object exists
            BACKFILL_CHUNKS_METRIC.labels(market=self.market, provider=self.provider, symbol=self.symbol).inc()
        logger.info(f"{log_prefix} Successfully processed and scheduled storage for {len(newly_fetched_bars)} bars.")
        return newly_fetched_bars