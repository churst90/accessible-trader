# services/subscription_worker.py

import asyncio
import logging
import random
from typing import Tuple, List, Dict, Any

from quart import current_app

from .subscription_registry import SubscriptionRegistry
from .subscription_lock import SubscriptionLock
from .broadcast_manager import BroadcastManager
from .market_service import MarketService
from plugins.base import PluginError

logger = logging.getLogger("SubscriptionWorker")

# Subscription key type alias
t_Key = Tuple[str, str, str, str]  # (market, provider, symbol, timeframe)

class SubscriptionWorker:
    """
    Runs a polling loop for a single subscription key, fetching new bars
    via MarketService.fetch_ohlcv and broadcasting to subscribers.
    Ensures only one loop runs per key via SubscriptionLock.
    """
    def __init__(
        self,
        registry: SubscriptionRegistry,
        market: str,
        provider: str,
        symbol: str,
        timeframe: str,
    ):
        self.registry = registry
        self.market = market
        self.provider = provider
        self.symbol = symbol
        self.timeframe = timeframe
        self.key: t_Key = (market, provider, symbol, timeframe)

        # MarketService provides fetch_ohlcv and backfill trigger
        self.service = MarketService(market, provider)

        # Internal control
        self._task: asyncio.Task = None  # Poll loop task
        self._stopped = asyncio.Event()

        # Compute poll interval from timeframe & config
        period_ms = int(self.timeframe[:-1]) * {
            'm': 60_000, 'h': 3_600_000, 'd': 86_400_000,
            'w': 604_800_000, 'M': 2_592_000_000, 'y': 31_536_000_000
        }.get(self.timeframe[-1], 60_000)
        cfg = current_app.config
        min_sec = cfg.get("MIN_POLL_INTERVAL_SEC", 5.0)
        max_sec = cfg.get("MAX_POLL_INTERVAL_SEC", 60.0)
        base = (period_ms / 1000.0) * 0.1
        self._interval = max(min_sec, min(max_sec, base))
        self._jitter = cfg.get("POLL_JITTER_FACTOR", 0.1)

    async def start(self) -> None:
        """
        Acquire the subscription lock and begin the poll loop in background.
        """
        await SubscriptionLock.acquire(*self.key)
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name=f"Worker_{self.key}")
        logger.info(f"SubscriptionWorker started for {self.key}")

    async def stop(self) -> None:
        """
        Cancel the poll loop and release the lock.
        """
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        SubscriptionLock.release(*self.key)
        self._stopped.set()
        logger.info(f"SubscriptionWorker stopped for {self.key}")

    async def _run(self) -> None:
        """
        Internal polling loop: fetch new bars, broadcast, sleep, repeat until no subscribers.
        """
        # Trigger background backfill if needed
        try:
            await self.service.orchestrator.trigger_historical_backfill_if_needed(
                self.symbol, self.timeframe
            )
        except Exception as e:
            logger.warning(f"Backfill trigger failed for {self.key}: {e}")

        last_ts = None  # track last timestamp seen
        while True:
            # If no subscribers remain, exit
            subs = self.registry.get_subscribers(*self.key)
            if not subs:
                break

            # Fetch any new bars since last_ts
            try:
                data = await self.service.fetch_ohlcv(
                    self.symbol,
                    self.timeframe,
                    since=last_ts,
                    before=None,
                    limit=None,
                )
            except PluginError as pe:
                logger.error(f"PluginError in worker for {self.key}: {pe}")
                data = None
            except Exception as ex:
                logger.exception(f"Unexpected error in worker for {self.key}: {ex}")
                data = None

            if data and data.get("ohlc"):
                # Update last_ts
                last_ts = data["ohlc"][-1][0]

                # Broadcast and handle dead sockets
                dead = await BroadcastManager.broadcast(
                    market=self.market,
                    provider=self.provider,
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    payload=data,
                    subscribers=subs,
                )
                for ws in dead:
                    self.registry.unregister(ws)

            # Sleep with jitter
            jitter = self._interval * self._jitter
            delay = max(0.1, self._interval + random.uniform(-jitter, jitter))
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=delay)
                break
            except asyncio.TimeoutError:
                continue

        # Clean up
        await self.stop()
