# services/backfill_manager.py

import asyncio
import logging
import time # Keep for int(time.time() * 1000)
from datetime import datetime, timezone # Keep for datetime.fromtimestamp
from typing import Dict, List, Optional, Tuple, Any

from quart import current_app
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type, RetryError
from prometheus_client import Counter, Gauge, REGISTRY
from plugins.base import MarketPlugin, PluginError
from utils.db_utils import DatabaseError, fetch_query, insert_ohlcv_to_db, has_data_in_range
from utils.timeframes import UNIT_MS # Used for calculating 'since_ms' in _run_historical_backfill

# Assuming 'Cache' is an ABC or a class that might cause circular import if imported directly
# from .cache_manager import Cache # If direct import is fine
# If using forward reference in __init__, ensure typing.TYPE_CHECKING for actual import if needed for methods

logger = logging.getLogger("BackfillManager")

# Global dictionaries for backfill tasks and locks, keyed by (market, provider, symbol)
_backfill_tasks: Dict[Tuple[str, str, str], asyncio.Task] = {}
_backfill_locks: Dict[Tuple[str, str, str], asyncio.Lock] = {}

# Optional Prometheus metrics
try:
    metric_name_chunks = "backfill_chunks_processed"
    if metric_name_chunks not in REGISTRY._metrics_to_collectors:
        BACKFILL_CHUNKS = Counter(
            metric_name_chunks, "Number of backfill chunks processed", ["market", "provider", "symbol"]
        )
    else:
        BACKFILL_CHUNKS = REGISTRY._metrics_to_collectors[metric_name_chunks]

    metric_name_gap = "backfill_data_gap_ms"
    if metric_name_gap not in REGISTRY._metrics_to_collectors:
        BACKFILL_GAP = Gauge(
            metric_name_gap, "Size of data gap in milliseconds", ["market", "provider", "symbol"]
        )
    else:
        BACKFILL_GAP = REGISTRY._metrics_to_collectors[metric_name_gap]
except (ImportError, AttributeError, ValueError, Exception) as e: # Broader catch for metric init
    logger.warning(f"Failed to initialize Prometheus metrics for BackfillManager: {e}")
    BACKFILL_CHUNKS = None
    BACKFILL_GAP = None


class BackfillManager:
    """
    Manages historical data backfills for 1-minute OHLCV bars.

    This class is responsible for:
    - Detecting if a data gap exists for a given market, provider, and symbol.
    - Triggering background tasks to fetch missing historical data from a plugin.
    - Handling data in chunks, storing it in the database, and potentially updating a cache.
    - Using locks to prevent concurrent backfill operations for the same asset.
    - Implementing retry mechanisms for transient errors during data fetching.
    """

    def __init__(
        self,
        market: str,
        provider: str,
        symbol: Optional[str], # Symbol can be None or empty at init, set later
        plugin: MarketPlugin,
        cache: Optional["Cache"],  # Forward reference for Cache type
    ):
        """
        Initializes the BackfillManager.

        Args:
            market (str): The market identifier (e.g., "crypto").
            provider (str): The data provider identifier (e.g., "binance").
            symbol (Optional[str]): The trading symbol (e.g., "BTC/USD").
                                    Can be initially None or empty and set later.
            plugin (MarketPlugin): An instance of a market data plugin.
            cache (Optional[Cache]): An instance of a cache manager (e.g., RedisCache).

        Raises:
            ValueError: If market or provider are not provided.
        """
        logger.debug(f"Initializing BackfillManager for {market}/{provider}, initial symbol: '{symbol}'")
        if not market or not provider:
            raise ValueError("BackfillManager: market and provider must be non-empty strings.")
        
        self.market = market
        self.provider = provider
        self.symbol = symbol or ""  # Ensure self.symbol is a string, even if empty
        self.plugin = plugin
        self.cache = cache # This is an instance of services.cache_manager.Cache (e.g. RedisCache)

        # Load configurations
        cfg = current_app.config
        try:
            self.plugin_chunk_size = int(cfg.get("DEFAULT_PLUGIN_CHUNK_SIZE", 500))
            self.max_backfill_chunks = int(cfg.get("MAX_BACKFILL_CHUNKS", 100))
            self.backfill_chunk_delay_sec = float(cfg.get("BACKFILL_CHUNK_DELAY_SEC", 1.5))
            self.default_backfill_period_ms = int(
                cfg.get("DEFAULT_BACKFILL_PERIOD_MS", 30 * 24 * 60 * 60 * 1000)  # 30 days
            )
        except ValueError as ve:
            logger.critical(f"Invalid configuration value for BackfillManager: {ve}", exc_info=True)
            raise ValueError(f"Configuration error for BackfillManager: {ve}") from ve


    async def trigger_historical_backfill_if_needed(self, timeframe_context: str) -> None:
        """
        Checks for historical data gaps and triggers a background backfill task if a gap is detected.
        Ensures only one backfill task runs per asset (market, provider, symbol) at a time.

        The `symbol` for this operation should be set on `self.symbol` before calling.

        Args:
            timeframe_context (str): The timeframe of the original request (used for logging context only).
                                     Backfill is always performed for '1m' data.
        Raises:
            ValueError: If `self.symbol` is not set.
        """
        if not self.symbol:
            logger.error(f"BackfillManager: Symbol not set for market={self.market}, provider={self.provider}. Cannot trigger backfill.")
            raise ValueError("Symbol must be set on BackfillManager before triggering backfill.")
        if not timeframe_context: # Though not used for logic, ensure it's provided for context
            logger.warning("BackfillTrigger: timeframe_context is missing.")
            # raise ValueError("Timeframe context must be non-empty for backfill trigger") # Or just log

        asset_key = (self.market, self.provider, self.symbol)
        active_task = _backfill_tasks.get(asset_key)

        if active_task and not active_task.done():
            logger.debug(f"Backfill task for {asset_key} is already running. Skipping trigger.")
            return

        target_oldest_ms = int(time.time() * 1000) - self.default_backfill_period_ms
        logger.debug(f"Checking for backfill need for {asset_key}, target oldest: {datetime.fromtimestamp(target_oldest_ms/1000.0, tz=timezone.utc)}")

        try:
            gap_is_present = await self._is_historical_data_gap_present(target_oldest_ms)
            
            if gap_is_present:
                lock = _backfill_locks.setdefault(asset_key, asyncio.Lock())
                
                if not lock.locked():
                    async with lock:
                        # Double-check task status after acquiring lock
                        if _backfill_tasks.get(asset_key) and not _backfill_tasks[asset_key].done():
                            logger.debug(f"Backfill for {asset_key} started by another coroutine while waiting for lock. Skipping.")
                            return

                        logger.info(f"BackfillTrigger: Gap detected. Starting backfill task for {asset_key} "
                                    f"aiming for data up to {datetime.fromtimestamp(target_oldest_ms/1000.0, tz=timezone.utc)}.")
                        task_name = f"Backfill_{self.provider}_{self.symbol}"
                        _backfill_tasks[asset_key] = asyncio.create_task(
                            self._run_historical_backfill(target_oldest_ms), name=task_name
                        )
                else:
                    logger.debug(f"Backfill for {asset_key}: Lock is held, another trigger might be active or recently finished.")
            else:
                logger.debug(f"BackfillTrigger: No significant gap found for {asset_key}.")
        except Exception as e: # Catch any exception from _is_historical_data_gap_present or lock logic
            logger.error(f"Error during backfill trigger process for {asset_key}: {e}", exc_info=True)


    async def _is_historical_data_gap_present(self, target_oldest_ms: int) -> bool:
        """
        Checks the database for the earliest 1m OHLCV bar for `self.symbol`
        and determines if it's more recent than `target_oldest_ms`.

        Args:
            target_oldest_ms: Timestamp (ms UTC) to compare against. A gap exists if
                              earliest data in DB is after this.

        Returns:
            True if a gap is detected (or no data found), False otherwise or on critical DB error.

        Raises:
            ValueError: If `self.symbol` is not set.
        """
        if not self.symbol:
            logger.error(f"BackfillManager: Symbol not set for _is_historical_data_gap_present on {self.market}/{self.provider}.")
            raise ValueError("Symbol required for gap check.") # Or return False if preferred

        logger.debug(f"Gap check for {self.symbol}, target: {datetime.fromtimestamp(target_oldest_ms/1000.0, tz=timezone.utc)}")
        earliest_db_ts_ms: Optional[int] = None
        rows = [] # Ensure rows is defined for logging in case of early exit
        try:
            rows = await fetch_query(
                "SELECT MIN(timestamp) AS min_ts FROM ohlcv_data "
                "WHERE market=$1 AND provider=$2 AND symbol=$3 AND timeframe='1m'",
                self.market, self.provider, self.symbol
            )
            if rows and rows[0] and rows[0].get('min_ts') is not None:
                min_ts_from_db = rows[0]['min_ts']
                if isinstance(min_ts_from_db, datetime):
                    earliest_db_ts_ms = int(min_ts_from_db.timestamp() * 1000)
                    logger.debug(f"Earliest 1m data in DB for {self.symbol}: {min_ts_from_db.replace(tzinfo=timezone.utc)}")
                else: # Should not happen if DB schema is correct
                    logger.warning(f"Unexpected type for min_ts for {self.symbol}: {type(min_ts_from_db)}. Assuming gap.")
                    return True 
            else: # No 1m data found in DB for this symbol
                logger.info(f"No 1m data found in DB for {self.symbol}. Gap detected.")
                return True
        except DatabaseError as dbe: # Custom DB error from db_utils
            logger.error(f"DB error during gap check for {self.symbol}: {dbe}", exc_info=True)
            return False # On DB error, assume no gap to prevent repeated failed attempts
        except (IndexError, KeyError, TypeError, AttributeError, ValueError) as e_data:
            logger.error(f"Data processing error during gap check for {self.symbol}: {e_data}. Raw rows: {rows}", exc_info=True)
            return False # Problem interpreting DB result, assume no gap
        except Exception as e: # Fallback
            logger.error(f"Unexpected error during gap check for {self.symbol}: {e}", exc_info=True)
            return False

        if earliest_db_ts_ms is None: # Should be caught by the "no data" case above, but as a safeguard
             logger.info(f"Could not determine earliest DB timestamp for {self.symbol}. Assuming gap.")
             return True

        gap_exists = earliest_db_ts_ms > (target_oldest_ms + UNIT_MS['d']) # Add a day buffer for significance
        if gap_exists and BACKFILL_GAP:
            BACKFILL_GAP.labels(market=self.market, provider=self.provider, symbol=self.symbol).set(
                earliest_db_ts_ms - target_oldest_ms
            )
        elif not gap_exists and BACKFILL_GAP: # Reset gauge if no gap
            BACKFILL_GAP.labels(market=self.market, provider=self.provider, symbol=self.symbol).set(0)
            
        return gap_exists


    async def _run_historical_backfill(self, target_oldest_ms: int) -> None:
        """
        Performs the historical data backfill for `self.symbol`.

        Runs as an asyncio Task, fetching 1-minute OHLCV data in chunks
        from the plugin, going backwards in time until `target_oldest_ms` is reached,
        the plugin provides no more data, or max chunks are processed.
        Data is inserted into DB and optionally cache.

        Args:
            target_oldest_ms: The oldest timestamp (ms UTC) to backfill to.
        
        Raises:
            ValueError: If `self.symbol` is not set when the method is called.
        """
        if not self.symbol:
            logger.error(f"BackfillManager: Symbol not set at start of _run_historical_backfill for {self.market}/{self.provider}. Aborting task.")
            # This state should ideally be prevented by the caller (DataOrchestrator)
            return

        asset_key = (self.market, self.provider, self.symbol)
        logger.info(f"Running backfill for {asset_key}, target oldest: {datetime.fromtimestamp(target_oldest_ms/1000.0, tz=timezone.utc)}.")
        
        current_earliest_ms: int
        chunk_num_completed = -1 # To correctly log number of attempted chunks

        try: # Outermost try for the entire backfill operation
            try: # Nested try for initial DB query
                rows = await fetch_query(
                    "SELECT MIN(timestamp) AS min_ts FROM ohlcv_data "
                    "WHERE market=$1 AND provider=$2 AND symbol=$3 AND timeframe='1m'",
                    self.market, self.provider, self.symbol
                )
                if rows and rows[0] and rows[0].get('min_ts') and isinstance(rows[0]['min_ts'], datetime):
                    current_earliest_ms = int(rows[0]['min_ts'].timestamp() * 1000)
                    logger.info(f"Backfill {asset_key}: Starting from DB earliest: {datetime.fromtimestamp(current_earliest_ms/1000.0, tz=timezone.utc)}")
                else:
                    current_earliest_ms = int(time.time() * 1000)
                    logger.info(f"Backfill {asset_key}: No 1m data in DB, starting from current time: {datetime.fromtimestamp(current_earliest_ms/1000.0, tz=timezone.utc)}")
            except DatabaseError as dbe:
                logger.error(f"Backfill {asset_key}: DB error on initial MIN(timestamp) fetch: {dbe}. Aborting backfill.", exc_info=True)
                return
            except (IndexError, KeyError, TypeError, AttributeError, ValueError) as e_conv:
                logger.error(f"Backfill {asset_key}: Error processing initial MIN(timestamp) from DB: {e_conv}. Aborting backfill.", exc_info=True)
                return

            for i in range(self.max_backfill_chunks):
                chunk_num_completed = i
                if current_earliest_ms <= target_oldest_ms:
                    logger.info(f"Backfill {asset_key}: Reached target oldest timestamp.")
                    break

                # Calculate 'since' for plugin: fetch a chunk ending *before* current_earliest_ms
                since_for_plugin_chunk = current_earliest_ms - (self.plugin_chunk_size * UNIT_MS['m'])
                
                fetched_bars = await self._process_backfill_chunk(
                    asset_key, chunk_num_completed, since_for_plugin_chunk, 
                    current_earliest_ms, target_oldest_ms
                )

                if not fetched_bars: # _process_backfill_chunk returns empty if no new older bars or plugin error limit reached
                    logger.info(f"Backfill {asset_key}: Chunk {chunk_num_completed + 1} yielded no new older bars. Ending backfill.")
                    break
                
                current_earliest_ms = fetched_bars[0]["timestamp"] # new_older_bars is sorted, [0] is earliest
                logger.info(
                    f"Backfill {asset_key}: Stored {len(fetched_bars)} new bars. "
                    f"New earliest is {datetime.fromtimestamp(current_earliest_ms/1000.0, tz=timezone.utc)}."
                )
                if BACKFILL_CHUNKS:
                    BACKFILL_CHUNKS.labels(market=self.market, provider=self.provider, symbol=self.symbol).inc()
                
                try:
                    await asyncio.sleep(self.backfill_chunk_delay_sec)
                except asyncio.CancelledError:
                    logger.info(f"Backfill {asset_key} cancelled during inter-chunk sleep.")
                    raise # Propagate cancellation

            logger.info(f"Backfill for {asset_key} finished main loop after {chunk_num_completed + 1} chunk(s).")

        except asyncio.CancelledError:
            logger.info(f"Backfill task for {asset_key} was cancelled.")
        except Exception as e: # Catch-all for unexpected errors in the main backfill logic
            logger.error(f"Critical unhandled error in backfill process for {asset_key}: {e}", exc_info=True)
        finally:
            _backfill_tasks.pop(asset_key, None)
            lock = _backfill_locks.get(asset_key)
            if lock and lock.locked():
                try:
                    lock.release()
                except RuntimeError as rle_lock:
                    logger.warning(f"Backfill {asset_key}: Error releasing lock (already unlocked or other issue): {rle_lock}")
            logger.info(f"Backfill task for {asset_key} fully cleaned up.")

    @retry(
        stop=stop_after_attempt(3), # Total 3 attempts for this chunk processing
        wait=wait_fixed(2),      # Wait 2 seconds between retries
        retry=retry_if_exception_type(PluginError), # Only retry on PluginError
        after=lambda rs: logger.warning(
            f"Backfill chunk for {rs.args[1] if len(rs.args) > 1 else 'unknown_asset'}: " # rs.args[1] is asset_key
            f"Retry attempt {rs.attempt_number} failed due to {rs.outcome.exception()}. "
            f"Next attempt in {rs.future.result() if rs.future else 'N/A'}s."
        ),
        reraise=True # Re-raise the exception after max attempts
    )
    async def _process_backfill_chunk(
        self,
        asset_key: Tuple[str, str, str],
        chunk_num_idx: int, # 0-indexed chunk number
        since_ms_for_plugin: int,
        current_db_earliest_ms: int,
        target_overall_oldest_ms: int,
    ) -> List[Dict[str, Any]]:
        """
        Processes a single chunk of historical data for backfill.

        Fetches data from the plugin, filters for new older bars, stores them in DB and cache.
        This method is decorated with `tenacity.retry` to handle transient PluginErrors.

        Args:
            asset_key: Identifier (market, provider, symbol).
            chunk_num_idx: The current chunk number (0-indexed, for logging).
            since_ms_for_plugin: The 'since' timestamp to pass to the plugin.
            current_db_earliest_ms: The earliest timestamp currently known in the database.
            target_overall_oldest_ms: The ultimate oldest timestamp the backfill aims for.

        Returns:
            A list of newly fetched and stored older bars, sorted chronologically.
            Returns an empty list if no new relevant bars are found or if a non-retriable error occurs.
        
        Raises:
            PluginError: If plugin fetching fails after all retries.
            DatabaseError: If storing data in the database fails.
            asyncio.CancelledError: If the task is cancelled.
        """
        if not self.symbol: # Should be set by _run_historical_backfill
             logger.error(f"BackfillManager._process_backfill_chunk: Symbol not set for {asset_key}. Aborting chunk.")
             raise ValueError("Symbol required for processing backfill chunk.")

        logger.debug(
            f"Backfill chunk {chunk_num_idx + 1} for {asset_key}: Fetching 1m since "
            f"{datetime.fromtimestamp(since_ms_for_plugin/1000.0, tz=timezone.utc)}, limit {self.plugin_chunk_size}"
        )

        # Check for existing data in the specific narrow range to avoid re-fetching already stored data.
        # This range is from where the plugin *might* start returning data up to our current earliest.
        try:
            if await has_data_in_range(
                self.market, self.provider, self.symbol, "1m", 
                since_ms_for_plugin, # From the start of the plugin's fetch window
                current_db_earliest_ms # Up to what we currently have
            ):
                logger.debug(f"Backfill chunk {chunk_num_idx + 1} for {asset_key}: Data already exists in target sub-range. "
                             "This might indicate overlapping fetch or very recent fill. Skipping this specific plugin fetch for safety.")
                # This could happen if a previous chunk slightly over-fetched or if another process is also backfilling.
                # Returning empty here prevents re-fetching/re-inserting the same very recent data.
                return [] 
        except DatabaseError as dbe_check:
            logger.warning(f"Backfill chunk {chunk_num_idx + 1} for {asset_key}: DB error checking for existing data in range: {dbe_check}. Proceeding with fetch.", exc_info=True)
        except ValueError as ve_check: # From has_data_in_range timestamp validation
            logger.warning(f"Backfill chunk {chunk_num_idx + 1} for {asset_key}: Value error checking data range: {ve_check}. Proceeding cautiously.", exc_info=True)


        # Fetch from plugin (this call is retried by tenacity on PluginError)
        bars_from_plugin = await self.plugin.fetch_historical_ohlcv(
            provider=self.provider, symbol=self.symbol, timeframe="1m",
            since=since_ms_for_plugin, limit=self.plugin_chunk_size,
        )

        if not bars_from_plugin:
            logger.info(f"Backfill chunk {chunk_num_idx + 1} for {asset_key}: Plugin returned no data.")
            return []

        # Filter for bars that are genuinely older than our current DB earliest AND within the overall target range
        new_older_bars = [
            b for b in bars_from_plugin
            if isinstance(b, dict) and \
               isinstance(b.get('timestamp'), int) and \
               b['timestamp'] < current_db_earliest_ms and \
               b['timestamp'] >= target_overall_oldest_ms
        ]

        if not new_older_bars:
            logger.info(f"Backfill chunk {chunk_num_idx + 1} for {asset_key}: No new *relevant older* bars found "
                        f"(plugin returned {len(bars_from_plugin)} total bars).")
            # Check if plugin is returning data newer than what we're looking for; might signal end of useful history.
            if any(b.get('timestamp', float('inf')) >= current_db_earliest_ms for b in bars_from_plugin if isinstance(b, dict)):
                logger.warning(f"Backfill {asset_key}: Plugin returned bars newer than or same as current DB earliest in chunk. "
                               "Considered end of useful history from plugin for this pass.")
            return [] # No new older bars to process

        new_older_bars.sort(key=lambda b_sort: b_sort['timestamp'])
        
        try:
            await insert_ohlcv_to_db(self.market, self.provider, self.symbol, "1m", new_older_bars)
            if self.cache and hasattr(self.cache, 'store_1m_bars'): # Check if cache and method exist
                # Fire-and-forget task for cache update
                asyncio.create_task(self.cache.store_1m_bars(self.market, self.provider, self.symbol, new_older_bars))
                logger.debug(f"Backfill chunk {chunk_num_idx + 1} for {asset_key}: Submitted {len(new_older_bars)} bars to cache.")
        except DatabaseError as dbe_insert:
            logger.error(f"Backfill chunk {chunk_num_idx + 1} for {asset_key}: DB error inserting {len(new_older_bars)} bars: {dbe_insert}. "
                         "This chunk will be considered failed.", exc_info=True)
            raise # Re-raise to be potentially caught by an outer loop or task handler if needed, but will stop this backfill run.
        except Exception as e_store: # Catch other unexpected errors during storage
            logger.error(f"Backfill chunk {chunk_num_idx + 1} for {asset_key}: Unexpected error storing {len(new_older_bars)} bars: {e_store}. "
                         "This chunk will be considered failed.", exc_info=True)
            raise # Re-raise

        return new_older_bars