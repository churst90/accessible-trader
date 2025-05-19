# services/subscription_service.py

import asyncio
import logging
from typing import Optional, Dict, Any

from quart import websocket
from plugins.base import PluginError

from .subscription_registry import SubscriptionRegistry, SubscriptionKey
from .subscription_lock import SubscriptionLock
from .subscription_worker import SubscriptionWorker
from .market_service import MarketService

logger = logging.getLogger("SubscriptionService")


class SubscriptionService:

    # Coordinates WebSocket subscribe/unsubscribe:
    # - Sends initial historical batch (one “data” message)
    # - Registers/ws in SubscriptionRegistry
    # - Spins up a SubscriptionWorker (poll loop) if not already running
    # - Cleans up on unsubscribe

    def __init__(self):
        self._registry = SubscriptionRegistry()
        self._workers: Dict[SubscriptionKey, SubscriptionWorker] = {}

    @staticmethod
    async def _send(ws, message: Dict[str, Any]) -> None:
        """
        Send a message via the WebSocket's send_queue if available, else direct send_json.
        """
        queue = getattr(ws, "_send_queue", None)
        if queue:
            await queue.put(message)
        else:
            # Fallback if _send_queue is not present, though the blueprint setup implies it should be.
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error(f"SubscriptionService: Error sending directly to WebSocket (no queue): {e}")


    async def subscribe(
        self,
        market: str,
        provider: str,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None
    ) -> None:
        """
        Handle a new websocket subscription:
          1) Validate & register
          2) Send initial batch (type="data" with initial_batch:true in payload)
          3) Start or reuse a SubscriptionWorker for live updates ("update")
        """
        ws = websocket._get_current_object()
        key = (market, provider, symbol, timeframe)

        # 1) register in our registry (unregistering any previous)
        self._registry.register(ws, market, provider, symbol, timeframe)
        logger.info(f"SubscriptionService: registered {ws} for {key}")

        # 2) Send initial batch
        svc = MarketService(market, provider)
        init_payload_from_market_service: Optional[Dict[str, Any]] = None
        status_message_for_client = f"Initial data for {symbol} ({timeframe}) on {provider}."

        try:
            # MarketService.fetch_ohlcv returns a dict like {"ohlc": [...], "volume": [...]}
            init_payload_from_market_service = await svc.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=since, # Pass client's 'since' for historical data point
                before=None, # We want data up to the present for initial load
                limit=None,  # MarketService/DataOrchestrator will use default_chart_points
            )
        except PluginError as pe:
            logger.error(f"SubscriptionService: PluginError fetching initial data for {key}: {pe}", exc_info=True)
            await self._send(ws, {
                "type": "error",
                "symbol": symbol, # Add symbol/timeframe context to error messages
                "timeframe": timeframe,
                "payload": {"message": f"Data provider error: {str(pe)}"}
            })
            self._registry.unregister(ws) # Clean up registration on error
            return
        except Exception: # Catch any other unexpected error from MarketService
            logger.exception(f"SubscriptionService: Unexpected error fetching initial data for {key}")
            await self._send(ws, {
                "type": "error",
                "symbol": symbol,
                "timeframe": timeframe,
                "payload": {"message": "Server error: Could not load initial chart data."}
            })
            self._registry.unregister(ws) # Clean up registration on error
            return

        # Construct the payload for the client, ensuring it includes the initial_batch flag
        # and that ohlc/volume are present, even if empty.
        client_message_payload = {
            "ohlc": init_payload_from_market_service.get("ohlc", []) if init_payload_from_market_service else [],
            "volume": init_payload_from_market_service.get("volume", []) if init_payload_from_market_service else [],
            "initial_batch": True,  # <<< CRITICAL FLAG FOR FRONTEND
            "status_message": status_message_for_client
        }

        # Immediately send exactly one "data" envelope with the structured payload
        await self._send(ws, {
            "type": "data",
            "symbol": symbol,
            "timeframe": timeframe,
            "payload": client_message_payload
        })
        logger.info(f"SubscriptionService: Sent initial_batch data for {key} to {ws}. Bars: {len(client_message_payload['ohlc'])}")


        # 3) Start or reuse worker
        # Check if a worker is already running for this key (e.g., another client subscribed)
        # and if its lock is still valid (meaning it's actively running or trying to).
        if key not in self._workers or not self._workers[key]._task or self._workers[key]._task.done():
            # If worker doesn't exist, or its task is done (e.g. errored out or completed unexpectedly),
            # try to start a new one. The worker itself handles the lock.
            logger.info(f"SubscriptionService: Attempting to start/restart worker for {key}.")
            worker = SubscriptionWorker(
                registry=self._registry,
                market=market,
                provider=provider,
                symbol=symbol,
                timeframe=timeframe
            )
            self._workers[key] = worker
            # The worker's start method will handle acquiring the lock.
            # If it can't acquire (e.g., another instance just got it), it won't run its loop.
            asyncio.create_task(worker.start(), name=f"StartWorker_{key}") # Non-blocking start
        else:
            logger.debug(f"SubscriptionService: Worker already seems to be active for {key}.")


    async def unsubscribe_current(self) -> None:
        """
        Remove the current ws from its subscription; if no subscribers remain,
        stop and discard the worker.
        """
        ws = websocket._get_current_object()
        key = self._registry.get_key_for_ws(ws)
        if not key:
            logger.debug(f"SubscriptionService: Attempted to unsubscribe a ws ({ws}) not found in registry.")
            return

        self._registry.unregister(ws)
        logger.info(f"SubscriptionService: unregistered {ws} from {key}")

        # Check if other subscribers remain for this specific key
        subscribers = self._registry.get_subscribers(*key)
        if not subscribers:
            logger.info(f"SubscriptionService: No more subscribers for {key}. Stopping worker.")
            worker = self._workers.pop(key, None)
            if worker:
                await worker.stop() # This will release the lock
                logger.info(f"SubscriptionService: stopped and removed worker for {key}")
            else:
                # This case might happen if the worker failed to start or was already removed.
                # Ensure the lock is released if it was somehow acquired by a defunct worker.
                SubscriptionLock.release(*key)
                logger.warning(f"SubscriptionService: No active worker found for {key} during unsubscribe cleanup, ensured lock release.")
        else:
            logger.info(f"SubscriptionService: {len(subscribers)} subscribers still active for {key}. Worker continues.")


    async def shutdown(self) -> None:
        """
        Gracefully stop all workers (e.g. on server shutdown).
        """
        logger.info(f"SubscriptionService: Shutting down all ({len(self._workers)}) workers...")
        # Create a list of stop tasks for all current workers
        # Iterating over items() to avoid issues if _workers is modified during shutdown by other means
        tasks = [worker.stop() for worker_key, worker in list(self._workers.items())]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    # Log which worker failed to stop, if possible to identify from tasks
                    logger.error(f"SubscriptionService: Error stopping a worker during shutdown: {result}")
        self._workers.clear() # Clear the dictionary of workers
        self._registry.clear_all() # Clear all registrations
        logger.info("SubscriptionService: All workers stopped and registry cleared.")