import asyncio
import logging
import random
import time
from typing import Dict, Set, Tuple, Optional, Any
from asyncio import Queue
from datetime import datetime, timezone

from quart import websocket
from quart.config import Config

from services.market_service import MarketService
from plugins.base import PluginError
from utils.timeframes import _parse_timeframe_str

logger = logging.getLogger("SubscriptionManager")

class SubscriptionManager:
    def __init__(self, app_config: Config):
        self._registry: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
        self._registry_lock = asyncio.Lock()
        self._cooldowns: Dict[Tuple[str, str, str, str], float] = {}
        self._last_sent_ts: Dict[Tuple[str, str, str, str], int] = {}
        self._failures: Dict[Tuple[str, str, str, str], int] = {}
        self._app_config = app_config
        
        self.default_initial_bars = self._app_config.get("DEFAULT_CHART_POINTS", 200)
        
        self.min_poll_interval_sec = self._app_config.get("MIN_POLL_INTERVAL_SEC", 5.0)
        self.max_poll_interval_sec = self._app_config.get("MAX_POLL_INTERVAL_SEC", 60.0)
        
        try:
            one_min_period_ms = _parse_timeframe_str("1m")[2]
        except ValueError:
            one_min_period_ms = 60000
        default_delay_base = max(
            self.min_poll_interval_sec,
            min(self.max_poll_interval_sec, (one_min_period_ms / 1000.0) * 0.1)
        )
        self.initial_poll_delay_sec = self._app_config.get("INITIAL_POLL_DELAY_SEC", default_delay_base + 2.0)
        
        self.max_poll_failures_before_backoff = self._app_config.get("MAX_POLL_FAILURES_BEFORE_BACKOFF", 5)
        self.poll_backoff_base_sec = self._app_config.get("POLL_BACKOFF_BASE_SEC", 5)
        self.max_poll_backoff_sec = self._app_config.get("MAX_POLL_BACKOFF_SEC", 300)
        self.poll_jitter_factor = self._app_config.get("POLL_JITTER_FACTOR", 0.1)
        logger.info(
            f"SubscriptionManager initialized. Default initial bars for WS: {self.default_initial_bars}, "
            f"Initial Poll Delay: {self.initial_poll_delay_sec:.1f}s"
        )

    async def subscribe(
        self,
        ws: websocket,
        market: str,
        provider: str,
        symbol: str,
        timeframe: str,
        client_since: Optional[int] = None
    ):
        key = (market, provider, symbol, timeframe)
        client_ws_key = ws.headers.get('sec-websocket-key', 'unknown_ws')
        log_prefix = f"SubMgr {client_ws_key} {key}:"

        effective_client_since = client_since if (client_since and client_since > 0) else 0
        logger.info(
            f"{log_prefix} Subscription attempt. client_since_param={client_since}, "
            f"effective_client_since_for_logic={effective_client_since if effective_client_since > 0 else 'None (fresh load)'}"
        )

        try:
            _parse_timeframe_str(timeframe)
        except ValueError as ve:
            logger.error(f"{log_prefix} Invalid timeframe '{timeframe}': {ve}")
            await ws.send_json({"type": "error", "symbol": symbol, "timeframe": timeframe,
                                "payload": {"message": f"Invalid timeframe format: {timeframe}"}})
            return

        try:
            svc = MarketService(market, provider)
        except ValueError as e:
            logger.error(
                f"{log_prefix} Failed to initialize MarketService for {market}/{provider}: {e}",
                exc_info=True
            )
            await ws.send_json({"type": "error", "symbol": symbol, "timeframe": timeframe,
                                "payload": {"message": f"Data provider or market unavailable: {str(e)}"}})
            return
        except Exception as e_ms_init:
            logger.error(
                f"{log_prefix} Unexpected error initializing MarketService for {market}/{provider}: {e_ms_init}",
                exc_info=True
            )
            await ws.send_json({"type": "error", "symbol": symbol, "timeframe": timeframe,
                                "payload": {"message": "Server error initializing data service."}})
            return

        async with self._registry_lock:
            entry = self._registry.get(key)
            if not entry:
                logger.info(f"{log_prefix} Creating new subscription entry.")
                entry = {"subs": set(), "queue": asyncio.Queue(), "market_service": svc}
                self._registry[key] = entry
                self._last_sent_ts[key] = effective_client_since
                self._failures[key] = 0
                self._cooldowns[key] = 0
            else:
                logger.debug(f"{log_prefix} Adding client to existing subscription.")
                entry["market_service"] = svc
            entry["subs"].add(ws)

        try:
            await ws.send_json({
                "type": "subscribed", "symbol": symbol, "timeframe": timeframe,
                "payload": {"message": "Subscription confirmed. Processing initial data..."}
            })
        except Exception as e_send_sub:
            logger.error(f"{log_prefix} Error sending 'subscribed' message: {e_send_sub}")
            async with self._registry_lock:
                if key in self._registry and ws in self._registry[key]["subs"]:
                    self._registry[key]["subs"].discard(ws)
                    if not self._registry[key]["subs"]:
                        logger.info(f"{log_prefix} Last client disconnected before ack. Cleaning up.")
                        task = self._registry[key].get("poll_task")
                        if task and not task.done(): task.cancel()
                        task = self._registry[key].get("bcast_task")
                        if task and not task.done(): task.cancel()
                        self._registry.pop(key, None)
                        self._cooldowns.pop(key, None)
                        self._last_sent_ts.pop(key, None)
                        self._failures.pop(key, None)
            return

        latest_ts_covered_for_this_client_setup = effective_client_since

        try:
            # Phase A & C combined for historical and catch-up
            is_fresh_load = not (effective_client_since > 0)
            fetch_since = None if is_fresh_load else effective_client_since
            limit = self.default_initial_bars if is_fresh_load else None

            logger.info(f"{log_prefix} Phase A: Fetching historical via fetch_ohlcv.")
            init_data = await svc.fetch_ohlcv(
                symbol, timeframe,
                since=fetch_since,
                limit=limit
            )
            ohlc = init_data.get("ohlc", [])
            vol = init_data.get("volume", [])

            logger.info(f"{log_prefix} Sending initial batch: {len(ohlc)} bars.")
            await ws.send_json({
                "type": "data", "symbol": symbol, "timeframe": timeframe,
                "payload": {"ohlc": ohlc, "volume": vol, "initial_batch": True}
            })

            if ohlc:
                latest_ts_covered_for_this_client_setup = ohlc[-1][0]

            async with self._registry_lock:
                self._last_sent_ts[key] = max(
                    self._last_sent_ts.get(key, 0),
                    latest_ts_covered_for_this_client_setup
                )

            logger.debug(f"{log_prefix} After historical, _last_sent_ts[{key}]={self._last_sent_ts[key]}")

            # Trigger backfill
            asyncio.create_task(svc.trigger_historical_backfill_if_needed(symbol, "1m"))

            # Phase D: start poll & broadcast
            async with self._registry_lock:
                entry = self._registry.get(key)
                if entry and ws in entry["subs"]:
                    if "poll_task" not in entry or entry["poll_task"].done():
                        entry["poll_task"] = asyncio.create_task(self._poll_loop(key, svc))
                    if "bcast_task" not in entry or entry["bcast_task"].done():
                        entry["bcast_task"] = asyncio.create_task(self._broadcaster_loop(key))
        except PluginError as e:
            logger.error(f"{log_prefix} PluginError during setup: {e}", exc_info=True)
            await ws.send_json({"type": "error", "symbol": symbol, "timeframe": timeframe,
                                "payload": {"message": f"Error obtaining data: {e}"}})
        except Exception as e_main:
            logger.exception(f"{log_prefix} Unexpected error during setup: {e_main}")
            try:
                await ws.send_json({"type": "error", "symbol": symbol, "timeframe": timeframe,
                                    "payload": {"message": "Server error occurred while preparing chart data."}})
            except Exception:
                logger.warning(f"{log_prefix} Could not notify client, WS may be closed.")

    async def unsubscribe(
        self,
        ws: websocket,
        market: str,
        provider: str,
        symbol: str,
        timeframe: str
    ):
        key = (market, provider, symbol, timeframe)
        client_ws_key = ws.headers.get('sec-websocket-key', 'unknown_ws')
        log_prefix = f"SubMgr {client_ws_key} {key}:"
        logger.info(f"{log_prefix} Unsubscription request.")

        async with self._registry_lock:
            entry = self._registry.get(key)
            if entry:
                entry["subs"].discard(ws)
                if not entry["subs"]:
                    task = entry.get("poll_task")
                    if task and not task.done(): task.cancel()
                    task = entry.get("bcast_task")
                    if task and not task.done(): task.cancel()
                    self._registry.pop(key, None)
                    self._cooldowns.pop(key, None)
                    self._last_sent_ts.pop(key, None)
                    self._failures.pop(key, None)
                    logger.info(f"{log_prefix} Resources released.")

    async def shutdown(self):
        logger.info("Shutting down SubscriptionManager...")
        tasks = []
        async with self._registry_lock:
            for key, entry in list(self._registry.items()):
                task = entry.get("poll_task")
                if task and not task.done():
                    task.cancel(); tasks.append(task)
                task = entry.get("bcast_task")
                if task and not task.done():
                    task.cancel(); tasks.append(task)
            self._registry.clear(); self._cooldowns.clear()
            self._last_sent_ts.clear(); self._failures.clear()
        if tasks:
            logger.info(f"Awaiting cancellation of {len(tasks)} background tasks...")
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("SubscriptionManager shutdown complete.")

    async def _broadcaster_loop(self, key: Tuple[str, str, str, str]):
        market, provider, symbol, timeframe = key
        log_prefix = f"BCAST {key}:"
        logger.info(f"{log_prefix} Starting broadcaster loop.")
        try:
            while True:
                async with self._registry_lock:
                    entry = self._registry.get(key)
                    if not entry:
                        logger.info(f"{log_prefix} Key removed. Exiting."); break
                    queue_instance = entry["queue"]
                    subs = list(entry["subs"])
                if not subs:
                    await asyncio.sleep(0.1); continue
                try:
                    msg = await asyncio.wait_for(queue_instance.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    logger.info(f"{log_prefix} Cancelled."); raise
                dead = set()
                for ws in subs:
                    try:
                        await ws.send_json(msg)
                    except Exception as e_send:
                        dead.add(ws)
                if msg: queue_instance.task_done()
                if dead:
                    async with self._registry_lock:
                        ent = self._registry.get(key)
                        if ent:
                            ent["subs"].difference_update(dead)
                            if not ent["subs"]:
                                task = ent.get("poll_task");
                                if task and not task.done(): task.cancel()
                                self._registry.pop(key, None); self._cooldowns.pop(key, None)
                                self._last_sent_ts.pop(key, None); self._failures.pop(key, None)
                                logger.info(f"{log_prefix} No subs left, exiting."); break
        except asyncio.CancelledError:
            logger.info(f"{log_prefix} Broadcaster cancelled.")
        except Exception:
            logger.exception(f"{log_prefix} Broadcaster crashed.")
        finally:
            logger.info(f"{log_prefix} Broadcaster finished.")

    async def _poll_loop(self, key: Tuple[str, str, str, str], svc: MarketService):
        market, provider, symbol, timeframe = key
        log_prefix = f"POLL {key}:"
        logger.info(f"{log_prefix} Starting poll loop.")
        try:
            _, _, period_ms = _parse_timeframe_str(timeframe)
            base_interval_sec = max(
                self.min_poll_interval_sec,
                min(self.max_poll_interval_sec, (period_ms / 1000.0) * 0.1)
            )
        except ValueError:
            logger.error(f"{log_prefix} Invalid timeframe '{timeframe}', exiting."); return

        logger.info(
            f"{log_prefix} Poll interval: {base_interval_sec:.1f}s, "
            f"initial delay: {self.initial_poll_delay_sec:.1f}s"
        )
        await asyncio.sleep(self.initial_poll_delay_sec)

        while True:
            current_time = time.time()
            async with self._registry_lock:
                entry = self._registry.get(key)
                if not entry:
                    logger.info(f"{log_prefix} Key removed, exiting poll."); break
                queue_instance = entry["queue"]
                last_ts = self._last_sent_ts.get(key, 0)
                cooldown_until = self._cooldowns.get(key, 0)

            if current_time < cooldown_until:
                await asyncio.sleep(max(0.1, cooldown_until - current_time)); continue

            try:
                # Use fetch_ohlcv to resample correctly for any timeframe
                data = await svc.fetch_ohlcv(
                    symbol,
                    timeframe,
                    since=last_ts,
                    limit=None
                )
                ohlc_list = data.get("ohlc", [])
                vol_list = data.get("volume", [])

                if ohlc_list:
                    for idx, bar in enumerate(ohlc_list):
                        ts, o, h, l, c = bar
                        vol = vol_list[idx][1] if idx < len(vol_list) else 0
                        payload = {
                            "type": "data",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "payload": {
                                "ohlc": [[ts, o, h, l, c]],
                                "volume": [[ts, vol]]
                            }
                        }
                        await queue_instance.put(payload)
                        async with self._registry_lock:
                            self._last_sent_ts[key] = ts
                            self._failures[key] = 0
                            self._cooldowns[key] = 0
                        logger.debug(
                            f"{log_prefix} Enqueued new bar (ts={ts}). "
                            f"_last_sent_ts[{key}]={ts}"
                        )
                        if timeframe == "1m":
                            # Save 1m bar
                            asyncio.create_task(
                                svc.save_recent_bars_to_db_and_cache(
                                    market, provider, symbol, "1m",
                                    [{"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": vol}]
                                )
                            )
                            logger.debug(
                                f"{log_prefix} Tasked saving new 1m bar (ts={ts})."
                            )
                else:
                    logger.debug(f"{log_prefix} No new bars from fetch_ohlcv.")
            except PluginError as pe:
                logger.error(f"{log_prefix} PluginError during poll: {pe}")
                async with self._registry_lock:
                    self._failures[key] = self._failures.get(key, 0) + 1
            except asyncio.CancelledError:
                logger.info(f"{log_prefix} Poll task cancelled."); raise
            except Exception as e:
                logger.exception(f"{log_prefix} Error in poll loop: {e}")
                async with self._registry_lock:
                    self._failures[key] = self._failures.get(key, 0) + 1

            # Backoff logic
            failures = self._failures.get(key, 0)
            if failures >= self.max_poll_failures_before_backoff:
                backoff = min(self.max_poll_backoff_sec,
                              self.poll_backoff_base_sec * (2 ** (failures - self.max_poll_failures_before_backoff)))
                logger.warning(f"{log_prefix} Failures={failures}, cooling down for {backoff:.1f}s.")
                async with self._registry_lock:
                    self._cooldowns[key] = time.time() + backoff
                try:
                    await queue_instance.put({
                        "type": "notice", "symbol": symbol, "timeframe": timeframe,
                        "payload": {"message": "Live updates delayed due to data source issues."}
                    })
                except Exception:
                    pass

            jitter = base_interval_sec * self.poll_jitter_factor
            await asyncio.sleep(max(0.1, base_interval_sec + random.uniform(-jitter, jitter)))

        logger.info(f"{log_prefix} Poll loop finished cleanly.")
