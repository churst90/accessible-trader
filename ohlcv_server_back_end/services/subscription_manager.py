# services/subscription_manager.py

import asyncio
import logging
import random
import time

from collections import defaultdict
from typing import Any, Dict, Tuple

from services.market_service import MarketService
from utils.db_utils import insert_ohlcv_to_db
from utils.timeframes import TIMEFRAME_PATTERN, UNIT_SEC

logger = logging.getLogger("SubscriptionManager")


class SubscriptionManager:
    def __init__(self):
        self._registry:     Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
        self._registry_lock = asyncio.Lock()
        self._key_locks     = defaultdict(lambda: asyncio.Lock())
        self._last_ts       = {}
        self._failures      = {}
        self._cooldowns     = {}

    async def subscribe(
        self,
        ws,
        market:    str,
        provider:  str,
        symbol:    str,
        timeframe: str,
        since:     int = None
    ):

        # Register a WS subscriber, send initial history after `since` (if given),
        # then start live polling/broadcast tasks.

        key = (market, provider, symbol, timeframe)
        async with self._registry_lock:
            entry = self._registry.get(key)
            if not entry:
                queue = asyncio.Queue()
                entry = {
                    "subs":       set(),
                    "queue":      queue,
                    "poll_task":  asyncio.create_task(self._poll_loop(key)),
                    "bcast_task": asyncio.create_task(self._broadcaster_loop(key)),
                }
                self._registry[key] = entry
            entry["subs"].add(ws)

        # Initialize last timestamp & failure counters
        self._last_ts.setdefault(key, 0)
        self._failures.setdefault(key, 0)

        # Acknowledge subscription
        await ws.send_json({
            "type":      "subscribed",
            "symbol":    symbol,
            "timeframe": timeframe,
            "payload":   {}
        })

        # Send initial history *after* `since`
        svc = MarketService(market, provider)
        try:
            H = await svc.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=since,
                limit=None
            )
        except Exception as e:
            await ws.send_json({
                "type":      "error",
                "symbol":    symbol,
                "timeframe": timeframe,
                "payload":   {
                    "message": "Failed to load initial history",
                    "details": str(e)
                }
            })
            return

        await ws.send_json({
            "type":      "data",
            "symbol":    symbol,
            "timeframe": timeframe,
            "payload":   {"ohlc": H["ohlc"], "volume": H["volume"]}
        })

        # Record the last timestamp sent
        if H["ohlc"]:
            self._last_ts[key] = H["ohlc"][-1][0]

    async def unsubscribe(
        self,
        ws,
        market:    str,
        provider:  str,
        symbol:    str,
        timeframe: str
    ):

        # Remove subscriber; if no one’s left, cancel tasks and clean up.

        key = (market, provider, symbol, timeframe)
        async with self._registry_lock:
            entry = self._registry.get(key)
            if not entry:
                return

            entry["subs"].discard(ws)
            await ws.send_json({
                "type":      "unsubscribed",
                "symbol":    symbol,
                "timeframe": timeframe,
                "payload":   {}
            })

            if not entry["subs"]:
                entry["poll_task"].cancel()
                entry["bcast_task"].cancel()
                del self._registry[key]
                self._last_ts.pop(key, None)
                self._failures.pop(key, None)
                self._cooldowns.pop(key, None)
                self._key_locks.pop(key, None)

    async def shutdown(self):

        # Called on server shutdown: cancel all loops.

        async with self._registry_lock:
            entries = list(self._registry.values())
            self._registry.clear()

        for e in entries:
            e["poll_task"].cancel()
            e["bcast_task"].cancel()

        await asyncio.gather(
            *(e["poll_task"] for e in entries),
            *(e["bcast_task"] for e in entries),
            return_exceptions=True
        )
        logger.info("SubscriptionManager shut down")

    async def _poll_loop(self, key: Tuple[str, str, str, str]):

        # Periodically fetch the latest bar and enqueue it if it’s new.

        market, provider, symbol, timeframe = key
        svc = MarketService(market, provider)

        # derive interval
        m = TIMEFRAME_PATTERN.match(timeframe)
        num, unit = int(m.group(1)), m.group(2)
        period = UNIT_SEC[unit] * num
        interval = max(5, period / 10)
        queue = self._registry[key]["queue"]

        logger.info("Poll loop for %s every %.1fs", key, interval)

        while True:
            try:
                now = time.time()
                cd = self._cooldowns.get(key, 0)
                if now < cd:
                    await asyncio.sleep(cd - now)
                    continue

                bar = await svc.fetch_latest_bar(symbol, timeframe)
                if bar and bar["timestamp"] > self._last_ts[key]:
                    await queue.put(bar)
                    self._last_ts[key] = bar["timestamp"]
                    try:
                        await insert_ohlcv_to_db(
                            market, provider, symbol, timeframe, [bar]
                        )
                    except Exception:
                        logger.exception(
                            "DB upsert failed in poll_loop for %s", key
                        )

                # reset failure counter
                self._failures[key] = 0

            except Exception as e:
                cnt = self._failures.get(key, 0) + 1
                self._failures[key] = cnt
                logger.exception("Poll error %s failure %d", key, cnt)
                if cnt >= 5:
                    backoff = min(period * 2, 300)
                    self._cooldowns[key] = time.time() + backoff
                    notice = {
                        "type":    "notice",
                        "message": "Live updates paused due to upstream errors."
                    }
                    await queue.put(notice)
                    self._failures[key] = 0

            finally:
                jitter = interval * 0.1
                await asyncio.sleep(interval + random.uniform(-jitter, jitter))

    async def _broadcaster_loop(self, key: Tuple[str, str, str, str]):

        # Take bars (or notices) from the queue in batches and push to all subscribers.

        _, _, symbol, timeframe = key
        queue = self._registry[key]["queue"]
        lock  = self._key_locks[key]

        while True:
            msg = await queue.get()

            # handle notice messages immediately
            if msg.get("type") == "notice":
                env = {
                    "type":      "notice",
                    "symbol":    symbol,
                    "timeframe": timeframe,
                    "payload":   {"message": msg["message"]}
                }
                async with lock:
                    subs = set(self._registry[key]["subs"])
                for ws in subs:
                    asyncio.create_task(ws.send_json(env))
                queue.task_done()
                continue

            # batch up as many bars as are available
            batch = [msg]
            try:
                while True:
                    nxt = queue.get_nowait()
                    if nxt.get("type") == "notice":
                        await queue.put(nxt)
                        break
                    batch.append(nxt)
            except asyncio.QueueEmpty:
                pass

            # construct the Highcharts payload
            ohlc   = [
                [b["timestamp"], b["open"], b["high"], b["low"], b["close"]]
                for b in batch
            ]
            volume = [
                [b["timestamp"], b["volume"]]
                for b in batch
            ]
            env = {
                "type":      "data",
                "symbol":    symbol,
                "timeframe": timeframe,
                "payload":   {"ohlc": ohlc, "volume": volume}
            }

            # broadcast to all current subscribers
            async with lock:
                subs = set(self._registry[key]["subs"])
            for ws in subs:
                asyncio.create_task(ws.send_json(env))

            queue.task_done()


# singleton instance
subscription_manager = SubscriptionManager()
