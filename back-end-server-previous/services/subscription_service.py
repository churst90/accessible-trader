# services/subscription_service.py

import asyncio
import logging
from typing import Optional, Dict, Any, List

from quart import websocket, current_app # For app.config and websocket context
from plugins.base import PluginError, OHLCVBar # For specific error handling and type hinting
from services.market_service import MarketService # For dependency injection
from services.subscription_registry import SubscriptionRegistry, SubscriptionKey
from services.subscription_lock import SubscriptionLock # To release lock if a worker fails catastrophically
from services.subscription_worker import SubscriptionWorker

logger = logging.getLogger(__name__) # Use __name__ for module-level logger

class SubscriptionService:
    """
    Coordinates WebSocket subscriptions for real-time market data.

    Responsibilities:
    - Managing client WebSocket connections and their subscriptions to specific data feeds
      (market, provider, symbol, timeframe).
    - Fetching and sending an initial batch of historical data upon a new subscription request,
      using the main MarketService instance.
    - Launching and managing SubscriptionWorker instances, which poll for live updates.
      Each worker is associated with a unique subscription key.
    - Handling unsubscriptions and ensuring resources (workers, locks) are cleaned up.
    """

    def __init__(self, market_service_instance: MarketService):
        """
        Initializes the SubscriptionService.

        Args:
            market_service_instance (MarketService): The application's single, pre-initialized
                                                     MarketService instance. This is crucial for
                                                     accessing data via the correct plugin configurations.
        """
        if not isinstance(market_service_instance, MarketService):
            raise TypeError(
                "SubscriptionService must be initialized with a valid MarketService instance."
            )
        
        self._registry = SubscriptionRegistry()
        self._workers: Dict[SubscriptionKey, SubscriptionWorker] = {}
        self.market_service: MarketService = market_service_instance
        logger.info("SubscriptionService initialized with MarketService instance.")

    @staticmethod
    async def _send_to_websocket(ws, message: Dict[str, Any]) -> bool:
        """
        Helper method to send a JSON message to a WebSocket client.

        Args:
            ws: The WebSocket connection object.
            message: The dictionary payload to send as JSON.
        
        Returns:
            bool: True if sending was successful, False otherwise.
        """
        try:
            # Assuming ws object is from Quart's WebSocket context
            await ws.send_json(message)
            return True
        except Exception as e:
            # Common exceptions: ConnectionClosed, or if socket is in a bad state.
            logger.warning(
                f"SubscriptionService: Error sending to WebSocket {ws.headers.get('sec-websocket-key', 'unknown_ws')}: {e}. "
                f"Client might have disconnected.", exc_info=False
            )
            return False

    async def subscribe(
        self,
        market: str,
        provider: str,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None, # Client can suggest a 'since' for initial data
        user_id: Optional[str] = None # For user-specific API keys via MarketService
    ) -> None:
        """
        Handles a new WebSocket subscription request from a client.

        Steps:
        1. Registers the WebSocket connection for the given subscription key.
        2. Fetches an initial batch of historical OHLCV data using `MarketService`.
           The data is formatted for Highcharts (ohlc and volume arrays).
        3. Sends this initial batch to the subscribing client.
        4. Starts a new `SubscriptionWorker` for the subscription key if one isn't already
           active, or informs the client that an existing worker will provide updates.

        Args:
            market (str): The market identifier (e.g., "crypto", "stocks").
            provider (str): The provider/exchange identifier (e.g., "binance", "alpaca").
            symbol (str): The trading symbol (e.g., "BTC/USDT", "AAPL").
            timeframe (str): The requested timeframe (e.g., "1m", "1h").
            since (Optional[int]): Optional start timestamp (ms UTC) for the initial data.
                                   If None, a default number of recent bars is fetched.
            user_id (Optional[str]): The ID of the authenticated user, if any, to allow
                                     MarketService to use user-specific API keys.
        """
        ws = websocket._get_current_object() # Get current WebSocket context
        client_ws_key = ws.headers.get('sec-websocket-key', 'unknown_ws') # For logging
        key: SubscriptionKey = (market, provider, symbol, timeframe)

        log_prefix = f"SubSvc Subscribe {client_ws_key} for {key}:"
        logger.info(f"{log_prefix} Received subscription request. User: {user_id}, Since: {since}.")

        self._registry.register(ws, market, provider, symbol, timeframe)
        logger.info(f"{log_prefix} WebSocket registered.")

        initial_bars_list: List[OHLCVBar] = []
        status_message = f"Subscribed. Fetching initial data for {symbol} ({timeframe}) on {provider}..."
        error_occurred = False

        try:
            await self._send_to_websocket(ws, {
                "type": "status", "symbol": symbol, "timeframe": timeframe,
                "payload": {"message": status_message, "status": "processing"}
            })

            # Fetch initial OHLCV data using the injected MarketService instance
            # MarketService.fetch_ohlcv returns List[OHLCVBar]
            initial_bars_list = await self.market_service.fetch_ohlcv(
                market=market,
                provider=provider,
                symbol=symbol,
                timeframe=timeframe,
                since=since, # Pass client's 'since' if provided
                until=None,  # Fetch up to the present for initial load
                limit=int(current_app.config.get("INITIAL_CHART_POINTS", 200)), # Configurable limit
                user_id=user_id,
                params=None # No special params for initial fetch by default
            )
            status_message = f"Initial data loaded for {symbol} ({timeframe}). {len(initial_bars_list)} bars."
            logger.info(f"{log_prefix} Initial data fetched. Bars: {len(initial_bars_list)}.")

        except PluginError as pe:
            logger.error(f"{log_prefix} PluginError fetching initial data: {pe}", exc_info=True)
            status_message = f"Error: Data provider issue - {str(pe)}"
            error_occurred = True
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error fetching initial data: {e}")
            status_message = "Error: Server issue loading initial chart data."
            error_occurred = True
        
        if error_occurred:
            await self._send_to_websocket(ws, {
                "type": "error", "symbol": symbol, "timeframe": timeframe,
                "payload": {"message": status_message}
            })
            self._registry.unregister(ws) # Clean up registration on error
            logger.warning(f"{log_prefix} Unregistered WebSocket due to error during initial data fetch.")
            return

        # Transform List[OHLCVBar] to Highcharts format
        ohlc_data_for_client: List[List[Any]] = []
        volume_data_for_client: List[List[Any]] = []
        if initial_bars_list:
            for bar in initial_bars_list:
                try:
                    ohlc_data_for_client.append([
                        bar['timestamp'], bar['open'], bar['high'], bar['low'], bar['close']
                    ])
                    volume_data_for_client.append([bar['timestamp'], bar['volume']])
                except KeyError as ke:
                    logger.error(f"{log_prefix} Bar data from MarketService missing key {ke}. Bar: {bar}", exc_info=False)
                    # Potentially skip this bar or send an error

        # Construct and send the initial data message to the client
        initial_payload_for_client = {
            "ohlc": ohlc_data_for_client,
            "volume": volume_data_for_client,
            "initial_batch": True, # Crucial flag for frontend to replace chart data
            "status_message": status_message
        }
        
        if not await self._send_to_websocket(ws, {
            "type": "data", "symbol": symbol, "timeframe": timeframe,
            "payload": initial_payload_for_client
        }):
            logger.warning(f"{log_prefix} Failed to send initial data to client. Unregistering.")
            self._registry.unregister(ws)
            return # Don't start worker if client is already gone

        logger.debug(f"{log_prefix} Sent initial_batch data to client.")

        # Start or reuse a SubscriptionWorker for this key
        # Lock is handled within the worker's start method
        if key not in self._workers or not self._workers[key]._task or self._workers[key]._task.done():
            logger.info(f"{log_prefix} No active worker found or worker task is done. Starting/Restarting worker.")
            worker = SubscriptionWorker(
                registry=self._registry,
                app_market_service=self.market_service, # Pass the main MarketService instance
                market=market,
                provider=provider,
                symbol=symbol,
                timeframe=timeframe,
                user_id=user_id # Pass user_id if workers need to be user-context aware for polling
            )
            self._workers[key] = worker
            # Worker.start() will attempt to acquire lock and run its poll loop.
            # Run as a background task.
            asyncio.create_task(worker.start(), name=f"StartWorker_{market}_{provider}_{symbol}_{timeframe}")
        else:
            logger.debug(f"{log_prefix} Worker already active. New client will receive updates from existing worker.")


    async def unsubscribe_current(self) -> None:
        """
        Handles unsubscription for the current WebSocket client.
        If no subscribers remain for a specific data feed (key), the corresponding
        SubscriptionWorker is stopped and removed.
        """
        ws = websocket._get_current_object()
        client_ws_key = ws.headers.get('sec-websocket-key', 'unknown_ws')
        key = self._registry.get_key_for_ws(ws)

        if not key:
            logger.debug(f"SubscriptionService Unsubscribe: WebSocket {client_ws_key} not found in registry. Already unsubscribed or never subscribed.")
            return

        log_prefix = f"SubSvc Unsubscribe {client_ws_key} from {key}:"
        logger.info(f"{log_prefix} Received unsubscription request.")

        self._registry.unregister(ws)
        logger.info(f"{log_prefix} WebSocket unregistered.")

        # Check if other subscribers remain for this specific key
        subscribers = self._registry.get_subscribers(*key) # Pass tuple elements as *args
        if not subscribers:
            logger.info(f"{log_prefix} No more subscribers for this key. Stopping and removing worker.")
            worker_to_stop = self._workers.pop(key, None) # Remove worker from tracking
            if worker_to_stop:
                try:
                    await worker_to_stop.stop() # stop() should handle task cancellation and lock release
                    logger.info(f"{log_prefix} Worker stopped and removed successfully.")
                except Exception as e_stop:
                    logger.error(f"{log_prefix} Error stopping worker: {e_stop}", exc_info=True)
                    # Ensure lock is released even if worker.stop() fails catastrophically
                    SubscriptionLock.release(*key)
            else:
                # If worker was already gone or never fully started, ensure lock is released.
                # This might happen if the worker failed to start or was cleaned up by another process.
                if SubscriptionLock.is_locked(*key):
                    logger.warning(f"{log_prefix} No active worker instance found, but lock was held. Releasing lock for {key}.")
                    SubscriptionLock.release(*key)
                else:
                    logger.debug(f"{log_prefix} No active worker instance found and lock not held for {key}.")
        else:
            logger.info(f"{log_prefix} {len(subscribers)} subscribers still active. Worker for {key} continues.")

    async def shutdown(self) -> None:
        """
        Gracefully stops all active SubscriptionWorkers and clears the registry.
        Typically called during application shutdown.
        """
        logger.info(f"SubscriptionService: Initiating shutdown of all ({len(self._workers)}) active workers...")
        
        # Create a list of stop tasks for all current workers
        # Iterate over items() to avoid issues if _workers is modified during iteration
        stop_tasks = [
            worker.stop() for worker_key, worker in list(self._workers.items()) if worker and worker._task and not worker._task.done()
        ]
        
        if stop_tasks:
            results = await asyncio.gather(*stop_tasks, return_exceptions=True)
            for i, result in enumerate(results): 
                # It might be hard to map result back to specific worker key here without more info
                if isinstance(result, Exception):
                    logger.error(f"SubscriptionService: Error stopping a worker during shutdown: {result}", exc_info=True)
        
        self._workers.clear() # Clear the dictionary of worker instances
        self._registry.clear_all() # Clear all client registrations
        logger.info("SubscriptionService: All workers stopped and client registry cleared. Shutdown complete.")