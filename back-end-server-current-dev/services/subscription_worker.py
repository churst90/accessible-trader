# services/subscription_worker.py

import asyncio
import logging
import random
from typing import Tuple, List, Dict, Any, Optional

from quart import current_app # For accessing app.config
from plugins.base import OHLCVBar, PluginError # For specific error handling and type hinting
from services.market_service import MarketService # For dependency injection
from services.subscription_registry import SubscriptionRegistry, SubscriptionKey
from services.subscription_lock import SubscriptionLock
from services.broadcast_manager import BroadcastManager # For sending updates to clients
from utils.timeframes import format_timestamp_to_iso

logger = logging.getLogger(__name__) # Use __name__ for module-level logger

class SubscriptionWorker:
    """
    A SubscriptionWorker is responsible for periodically polling for new OHLCV (Open, High, Low, Close, Volume)
    data for a single, specific subscription key (market, provider, symbol, timeframe).
    It uses an injected MarketService instance to fetch the data.

    Once new data is fetched, it's formatted for Highcharts and then broadcasted
    to all subscribed WebSocket clients via the BroadcastManager.

    Each worker ensures that only one polling loop runs per unique subscription key
    across the application instance by acquiring a SubscriptionLock.
    The worker's lifecycle (start, stop) is managed by the SubscriptionService.
    """

    def __init__(
        self,
        registry: SubscriptionRegistry,
        app_market_service: MarketService, # Renamed for clarity from original file
        market: str,
        provider: str,
        symbol: str,
        timeframe: str,
        user_id: Optional[str] = None # For user-specific data polling if applicable
    ):
        """
        Initializes the SubscriptionWorker.

        Args:
            registry (SubscriptionRegistry): The central registry of WebSocket subscriptions.
            app_market_service (MarketService): The main application's MarketService instance.
            market (str): The market identifier for this worker's subscription.
            provider (str): The provider/exchange identifier.
            symbol (str): The trading symbol.
            timeframe (str): The timeframe for the OHLCV data.
            user_id (Optional[str]): The user ID, if this subscription is user-specific.
                                     Passed to MarketService for data fetching.
        """
        if not isinstance(registry, SubscriptionRegistry):
            raise TypeError("SubscriptionWorker requires a valid SubscriptionRegistry instance.")
        if not isinstance(app_market_service, MarketService):
            raise TypeError("SubscriptionWorker requires a valid MarketService instance.")

        self.registry: SubscriptionRegistry = registry
        self.market_service: MarketService = app_market_service
        self.market: str = market
        self.provider: str = provider
        self.symbol: str = symbol
        self.timeframe: str = timeframe
        self.user_id: Optional[str] = user_id
        self.key: SubscriptionKey = (market, provider, symbol, timeframe) # Standardized key

        self._task: Optional[asyncio.Task] = None  # The asyncio Task for the _run loop
        self._stopped = asyncio.Event() # Event to signal the worker to stop

        # Calculate polling interval based on timeframe and app configuration
        try:
            # Attempt to parse timeframe to get its duration in milliseconds
            # This logic is similar to what was in the "screwed up" version
            tf_value_str = self.timeframe[:-1]
            if not tf_value_str.isdigit(): # Basic validation
                raise ValueError(f"Invalid numeric part in timeframe: '{tf_value_str}' from '{self.timeframe}'")
            
            period_multiplier = int(tf_value_str)
            unit_char = self.timeframe[-1].lower() # Ensure lowercase for map lookup
            
            # Standard millisecond values per unit
            unit_ms_map: Dict[str, int] = {
                's': 1_000,      # Seconds (if ever supported)
                'm': 60_000,     # Minute
                'h': 3_600_000,  # Hour
                'd': 86_400_000, # Day
                'w': 604_800_000,# Week
                'M': 2_592_000_000 # Month (approx. 30 days)
            }
            if unit_char not in unit_ms_map:
                raise ValueError(f"Unsupported timeframe unit: '{unit_char}' in '{self.timeframe}'")
            
            timeframe_duration_ms = period_multiplier * unit_ms_map[unit_char]
        except ValueError as e_tf_parse:
            logger.error(
                f"SubscriptionWorker {self.key}: Invalid timeframe format '{self.timeframe}' for interval calculation: {e_tf_parse}. "
                f"Defaulting poll interval calculation period to 1 minute (60000 ms)."
            )
            timeframe_duration_ms = 60_000 # Default to 1 minute duration for interval calc
        
        cfg = current_app.config
        min_poll_interval_s: float = float(cfg.get("MIN_POLL_INTERVAL_SEC", 5.0))
        max_poll_interval_s: float = float(cfg.get("MAX_POLL_INTERVAL_SEC", 60.0))
        # Poll at a fraction of the timeframe duration (e.g., 10% of a 1-minute bar = 6 seconds)
        poll_interval_fraction: float = float(cfg.get("POLL_INTERVAL_TIMEFRAME_FRACTION", 0.1))
        
        calculated_base_interval_s = (timeframe_duration_ms / 1000.0) * poll_interval_fraction
        
        # Clamp the interval within configured min/max bounds
        self._poll_interval_seconds: float = max(min_poll_interval_s, min(max_poll_interval_s, calculated_base_interval_s))
        self._poll_jitter_factor: float = float(cfg.get("POLL_JITTER_FACTOR", 0.1)) # e.g., 10% jitter

        logger.debug(
            f"SubscriptionWorker {self.key} initialized. "
            f"Timeframe duration: {timeframe_duration_ms}ms. "
            f"Calculated poll interval: {self._poll_interval_seconds:.2f}s (jitter factor: {self._poll_jitter_factor:.2f})."
        )

    async def start(self) -> None:
        """
        Acquires the subscription-specific lock and starts the polling loop (_run)
        as an asyncio Task. If the lock cannot be acquired (e.g., another worker
        for the same key is already running), this method will not start a new task.
        """
        log_prefix = f"Worker Start {self.key}:"
        logger.info(f"{log_prefix} Attempting to start...")

        lock_acquired_by_this_worker = False
        try:
            # Check if lock is already held to avoid unnecessary blocking if acquire has no timeout
            if SubscriptionLock.is_locked(*self.key):
                logger.info(f"{log_prefix} Lock is already held by another worker. Start aborted.")
                return

            await SubscriptionLock.acquire(*self.key)
            lock_acquired_by_this_worker = True
            logger.info(f"{log_prefix} Lock acquired.")

            self._stopped.clear() # Clear stop signal from previous runs, if any
            self._task = asyncio.create_task(
                self._run(),
                name=f"SubWorker_{self.market}_{self.provider}_{self.symbol}_{self.timeframe}"
            )
            logger.info(f"{log_prefix} Polling task '{self._task.get_name()}' created and started.")

        except Exception as e_start:
            logger.error(f"{log_prefix} Failed to acquire lock or start polling task: {e_start}", exc_info=True)
            if lock_acquired_by_this_worker:
                # This worker acquired the lock but failed to start its task, so release it.
                SubscriptionLock.release(*self.key)
                logger.info(f"{log_prefix} Lock released due to task start failure.")

    async def stop(self) -> None:
        """
        Signals the polling loop to stop, cancels the underlying asyncio Task,
        and attempts to release the subscription lock.
        """
        log_prefix = f"Worker Stop {self.key}:"
        logger.info(f"{log_prefix} Initiating stop sequence...")
        self._stopped.set() # Signal the _run loop to terminate

        if self._task and not self._task.done():
            logger.debug(f"{log_prefix} Cancelling polling task '{self._task.get_name()}'.")
            self._task.cancel()
            try:
                await self._task # Wait for the task to acknowledge cancellation
            except asyncio.CancelledError:
                logger.info(f"{log_prefix} Polling task '{self._task.get_name()}' was cancelled successfully.")
            except Exception as e_task_await:
                # This might happen if the task had an unhandled error during its cancellation
                logger.error(f"{log_prefix} Error encountered while awaiting cancelled task: {e_task_await}", exc_info=True)
        else:
            logger.debug(f"{log_prefix} No active polling task to cancel or task already done.")
        
        # The lock should ideally be released in the `finally` block of the `_run` method.
        # However, calling release here acts as a safeguard if `_run` didn't get to its
        # finally block or if stop is called for other reasons.
        # SubscriptionLock.release is idempotent if called when not locked by current context in some impls,
        # but our simple lock just releases if locked.
        if SubscriptionLock.is_locked(*self.key): # Check if lock is held before attempting release by this context
             # This check might be tricky if the lock isn't context-aware (i.e. who holds it)
             # For simplicity, we assume if stop() is called, this worker *might* have been the holder.
             # The _run method's finally block is the primary releaser.
            logger.debug(f"{log_prefix} Attempting to release lock as part of stop sequence (primary release in _run's finally).")
            SubscriptionLock.release(*self.key)
        
        self._task = None # Clear the task reference
        logger.info(f"{log_prefix} Stop sequence complete.")


    async def _run(self) -> None:
        """
        The main polling loop for this worker.
        Continuously fetches new OHLCV data since the last seen timestamp,
        formats it for Highcharts, and broadcasts it to subscribers.
        This loop runs until an external stop is signaled or no subscribers remain.
        The subscription lock is released in the `finally` block of this method.
        """
        log_prefix = f"Worker Run {self.key}:"
        logger.info(f"{log_prefix} Polling loop starting.")
        last_seen_timestamp_ms: Optional[int] = None # Track the timestamp of the last bar sent

        try:
            # Trigger initial backfill check for the symbol if MarketService supports it
            logger.debug(f"{log_prefix} Triggering initial historical backfill check (if needed).")
            await self.market_service.trigger_historical_backfill_if_needed(
                market=self.market,
                provider=self.provider,
                symbol=self.symbol,
                timeframe_context=self.timeframe, # For logging/context within backfill
                user_id=self.user_id
            )
        except Exception as e_backfill_trigger:
            logger.warning(f"{log_prefix} Initial backfill trigger failed: {e_backfill_trigger}", exc_info=True)

        try:
            while not self._stopped.is_set():
                current_subscribers = self.registry.get_subscribers(*self.key)
                if not current_subscribers:
                    logger.info(f"{log_prefix} No active subscribers. Exiting polling loop.")
                    break # Exit loop if no one is listening

                fetched_ohlcv_bars: List[OHLCVBar] = [] # Stores List[OHLCVBar]
                try:
                    # Fetch new data since the last bar we sent.
                    # MarketService.fetch_ohlcv should ideally handle "since" inclusively or allow us
                    # to specify. If it's inclusive, `last_seen_timestamp_ms + 1` is fine for ms.
                    fetch_since = (last_seen_timestamp_ms + 1) if last_seen_timestamp_ms is not None else None
                    
                    logger.debug(f"{log_prefix} Polling for new data. Since: {fetch_since} ({format_timestamp_to_iso(fetch_since) if fetch_since else 'None'}).")
                    fetched_ohlcv_bars = await self.market_service.fetch_ohlcv(
                        market=self.market,
                        provider=self.provider,
                        symbol=self.symbol,
                        timeframe=self.timeframe,
                        since=fetch_since,
                        until=None, # For live updates, poll up to current time
                        # Limit for updates: usually small, e.g., few bars to catch up missed ones + latest
                        # Or None to let MarketService decide a sensible default for updates.
                        limit=int(current_app.config.get("SUBSCRIPTION_UPDATE_FETCH_LIMIT", 10)),
                        user_id=self.user_id,
                        params=None # No special params for polling by default
                    )
                except PluginError as pe:
                    logger.error(f"{log_prefix} PluginError during data fetch: {pe}")
                    # Continue to sleep and retry, or implement backoff for persistent errors
                except Exception as ex_fetch:
                    logger.exception(f"{log_prefix} Unexpected error during data fetch: {ex_fetch}")
                    # Continue to sleep and retry
                
                new_bars_to_broadcast_count = 0
                if fetched_ohlcv_bars:
                    ohlc_data_for_client: List[List[Any]] = []
                    volume_data_for_client: List[List[Any]] = []
                    
                    # Sort just in case, though MarketService should return sorted
                    # fetched_ohlcv_bars.sort(key=lambda b: b['timestamp'])

                    for bar in fetched_ohlcv_bars:
                        # Ensure we only broadcast bars strictly newer than what was last sent
                        if last_seen_timestamp_ms is None or bar['timestamp'] > last_seen_timestamp_ms:
                            try:
                                ohlc_data_for_client.append([
                                    bar['timestamp'], bar['open'], bar['high'], bar['low'], bar['close']
                                ])
                                volume_data_for_client.append([bar['timestamp'], bar['volume']])
                                
                                # Update last_seen_timestamp_ms to the timestamp of this new bar
                                last_seen_timestamp_ms = bar['timestamp']
                                new_bars_to_broadcast_count +=1
                            except KeyError as ke:
                                logger.error(f"{log_prefix} Data for broadcasting malformed. Missing key: {ke}. Bar: {bar}", exc_info=False)
                                continue # Skip this malformed bar
                    
                    if new_bars_to_broadcast_count > 0:
                        logger.info(f"{log_prefix} Processed {new_bars_to_broadcast_count} new bars. Last timestamp sent: {last_seen_timestamp_ms}. Broadcasting...")
                        update_payload_for_client = {
                            "ohlc": ohlc_data_for_client,
                            "volume": volume_data_for_client,
                            "initial_batch": False # This is an update
                        }
                        dead_ws_list = await BroadcastManager.broadcast(
                            market=self.market, provider=self.provider,
                            symbol=self.symbol, timeframe=self.timeframe,
                            payload=update_payload_for_client,
                            subscribers=list(current_subscribers) # Pass current list
                        )
                        if dead_ws_list:
                            logger.info(f"{log_prefix} Found {len(dead_ws_list)} dead WebSockets during broadcast. Unregistering them.")
                            for ws in dead_ws_list:
                                self.registry.unregister(ws) # Unregister dead clients
                    elif fetched_ohlcv_bars: # Data fetched, but nothing *newer* than last_seen
                        logger.debug(f"{log_prefix} Data fetched, but no bars newer than {last_seen_timestamp_ms} to broadcast.")
                else: # No data fetched at all
                    logger.debug(f"{log_prefix} No data returned from MarketService in this poll cycle.")

                # Calculate sleep duration with jitter
                jitter_value_s = self._poll_interval_seconds * self._poll_jitter_factor * random.uniform(-1, 1)
                current_sleep_duration_s = max(0.1, self._poll_interval_seconds + jitter_value_s) # Ensure positive sleep
                
                logger.debug(f"{log_prefix} Sleeping for {current_sleep_duration_s:.2f} seconds.")
                try:
                    # Wait for the sleep duration, but break early if _stopped is set
                    await asyncio.wait_for(self._stopped.wait(), timeout=current_sleep_duration_s)
                    # If _stopped.wait() returned (didn't timeout), it means stop was signaled.
                    logger.info(f"{log_prefix} Stop signal received during sleep. Exiting polling loop.")
                    break 
                except asyncio.TimeoutError:
                    continue # Timeout means sleep completed, continue to next poll
                except asyncio.CancelledError:
                    logger.info(f"{log_prefix} Polling loop task cancelled during sleep.")
                    raise # Propagate cancellation
        
        except asyncio.CancelledError:
            logger.info(f"{log_prefix} Polling loop task was cancelled externally.")
        except Exception as e_run_loop:
            # Catch any other unhandled critical error in the loop itself
            logger.error(f"{log_prefix} Unhandled exception in main polling loop: {e_run_loop}", exc_info=True)
        finally:
            logger.info(f"{log_prefix} Polling loop and worker run method terminated. Releasing lock.")
            SubscriptionLock.release(*self.key) # Crucial: release lock when worker stops or errors