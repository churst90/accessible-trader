# services/market_service.py

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from quart import current_app
from plugins import PluginLoader
from plugins.base import PluginError
from utils.db_utils import fetch_query, fetch_ohlcv_from_db, insert_ohlcv_to_db
from utils.timeframes import TIMEFRAME_PATTERN, UNIT_MS

logger = logging.getLogger("MarketService")


def _parse_timeframe(tf: str) -> Tuple[int, str]:
    m = TIMEFRAME_PATTERN.match(tf)
    if not m:
        raise ValueError(f"Invalid timeframe '{tf}'")
    num, unit = int(m.group(1)), m.group(2)
    if num <= 0:
        raise ValueError("Timeframe must be > 0")
    return num, unit


def _resample(raw: List[Dict[str, Any]], tf: str) -> List[Dict[str, Any]]:
    """
    Bucket a list of 1m bars into the desired timeframe tf.
    """
    num, unit = _parse_timeframe(tf)
    period_ms = UNIT_MS[unit] * num
    buckets: Dict[int, Dict[str, Any]] = {}

    for bar in raw:
        ts = bar["timestamp"]
        start = ts - (ts % period_ms)
        slot = buckets.setdefault(start, {
            "timestamp": start,
            "open":      bar["open"],
            "high":      bar["high"],
            "low":       bar["low"],
            "close":     bar["close"],
            "volume":    bar["volume"],
        })
        slot["high"]   = max(slot["high"],  bar["high"])
        slot["low"]    = min(slot["low"],   bar["low"])
        slot["close"]  = bar["close"]
        slot["volume"] += bar["volume"]

    return [buckets[t] for t in sorted(buckets)]


def _dedupe(
    ohlc: List[List[Any]],
    vol:  List[List[Any]]
) -> Tuple[List[List[Any]], List[List[Any]]]:
    """
    Remove duplicate timestamps.
    """
    seen = set()
    o2, v2 = [], []
    for o, v in zip(ohlc, vol):
        ts = o[0]
        if ts not in seen:
            seen.add(ts)
            o2.append(o)
            v2.append(v)
    return o2, v2


class MarketService:
    def __init__(self, market: str, provider: str):
        self.market   = market
        self.provider = provider

        try:
            if market == "crypto":
                self.plugin = PluginLoader.load_plugin("crypto")
            else:
                self.plugin = PluginLoader.load_plugin(provider)
                if market not in getattr(self.plugin, "supported_markets", []):
                    raise ValueError(
                        f"Provider '{provider}' does not support market '{market}'"
                    )
        except PluginError as e:
            raise ValueError(f"Provider unavailable: {e}") from e

        self._preagg: Optional[Dict[str, str]] = None


    async def _load_preaggregates(self) -> Dict[str, str]:
        """
        Caches { timeframe_str: continuous_view_name }.
        """
        if self._preagg is not None:
            return self._preagg

        self._preagg = {}
        try:
            rows = await fetch_query("""
                SELECT view_name
                  FROM timescaledb_information.continuous_aggregates
                 WHERE view_name LIKE 'ohlcv_%'
            """)
            for r in rows:
                view = r["view_name"]               # e.g. "ohlcv_15min"
                raw  = view.split("ohlcv_",1)[1]    # e.g. "15min"
                tf   = (raw
                        .replace("min",   "m")
                        .replace("hour",  "h")
                        .replace("day",   "d")
                        .replace("week",  "w")
                        .replace("month", "M")
                        .replace("year",  "y"))
                self._preagg[tf] = view
            logger.info("Loaded continuous aggregates: %s",
                        sorted(self._preagg.keys()))
        except Exception as e:
            logger.warning("Could not load continuous aggregates: %s", e)
            self._preagg = {}

        return self._preagg


    async def get_symbols(self) -> List[str]:
        return await self.plugin.get_symbols(self.provider)


    async def fetch_ohlcv(
        self,
        symbol:    str,
        timeframe: str                   = "1m",
        since:     Optional[int]         = None,
        before:    Optional[int]         = None,
        limit:     Optional[int]         = None
    ) -> Dict[str, List[List[Any]]]:
        cache = current_app.config.get("CACHE")

        # —— 1m bar path —— #
        if timeframe == "1m":
            cache_key = f"latest:ohlcv:{self.market}:{self.provider}:{symbol}:1m"

            # 1) Try Redis cache when no 'since'
            if cache and since is None:
                try:
                    last = await cache.get(cache_key)
                    if last:
                        ts = last["timestamp"]
                        return {
                            "ohlc":   [[ts, last["open"], last["high"],
                                        last["low"], last["close"]]],
                            "volume": [[ts, last["volume"]]]
                        }
                except Exception as e:
                    logger.error("Redis get error: %s", e)

            # 2) If still no since, get MAX(timestamp) from DB
            if since is None:
                try:
                    row = await fetch_query(
                        "SELECT MAX(timestamp) AS ts "
                        "FROM ohlcv_data "
                        "WHERE market=$1 AND provider=$2 AND symbol=$3 "
                        "AND timeframe='1m'",
                        self.market, self.provider, symbol
                    )
                    ts = row and row[0].get("ts")
                    if ts:
                        since = int(ts.timestamp() * 1000)
                except Exception as e:
                    logger.error("DB error fetching max timestamp: %s", e)

            # 3) Pull raw from DB
            try:
                raw = await fetch_ohlcv_from_db(
                    self.market, self.provider, symbol,
                    "1m", since, limit
                )
            except Exception as e:
                logger.error("DB error in fetch_ohlcv_from_db: %s", e)
                raw = []

            # 4) Apply 'before' filter
            if before is not None:
                raw = [b for b in raw if b["timestamp"] < before]

            # 5) Decide if plugin fallback is needed
            need_plugin = False
            if not raw:
                need_plugin = True
            elif since is not None:
                need_plugin = True
            elif limit is not None and len(raw) < limit:
                need_plugin = True

            if need_plugin:
                try:
                    plugin_data = await self.plugin.fetch_historical_ohlcv(
                        self.provider, symbol, "1m",
                        since=since, before=before, limit=limit or 500
                    )
                    if plugin_data:
                        raw = plugin_data
                        await insert_ohlcv_to_db(
                            self.market, self.provider, symbol, "1m", raw
                        )
                except Exception as e:
                    logger.error("Plugin fetch error: %s", e)
                    # if DB had some data, keep it

            # 6) Cache latest
            if cache and raw:
                try:
                    await cache.set(cache_key, raw[-1], expire=3600)
                except Exception as e:
                    logger.error("Redis set error: %s", e)

            # 7) Format + dedupe
            ohlc = [[b["timestamp"], b["open"],  b["high"],
                     b["low"],         b["close"]] for b in raw]
            vol  = [[b["timestamp"], b["volume"]] for b in raw]
            ohlc, vol = _dedupe(ohlc, vol)
            return {"ohlc": ohlc, "volume": vol}


        # —— non-1m: try continuous-agg view —— #
        try:
            preagg = await self._load_preaggregates()
        except Exception:
            preagg = {}

        if timeframe in preagg:
            view    = preagg[timeframe]
            clauses = ["market=$1", "provider=$2", "symbol=$3"]
            params  = [self.market, self.provider, symbol]
            idx     = 4

            if since  is not None:
                clauses.append(f"bucketed_time >= ${idx}")
                params.append(
                    datetime.fromtimestamp(since/1000, tz=timezone.utc)
                )
                idx += 1
            if before is not None:
                clauses.append(f"bucketed_time < ${idx}")
                params.append(
                    datetime.fromtimestamp(before/1000, tz=timezone.utc)
                )
                idx += 1

            limit_sql = f"LIMIT ${idx}" if limit is not None else ""
            if limit is not None:
                params.append(limit)

            sql = f"""
                SELECT bucketed_time AS ts, open, high, low, close, volume
                  FROM {view}
                 WHERE {' AND '.join(clauses)}
              ORDER BY bucketed_time DESC
                {limit_sql}
            """
            try:
                rows = await fetch_query(sql, *params)
                rows = list(reversed(rows))
            except Exception as e:
                logger.error("DB error fetching continuous-agg: %s", e)
                rows = []

            if rows:
                ohlc = [
                    [int(r["ts"].timestamp() * 1000),
                     r["open"], r["high"], r["low"], r["close"]]
                    for r in rows
                ]
                vol = [
                    [int(r["ts"].timestamp() * 1000), r["volume"]]
                    for r in rows
                ]
                ohlc, vol = _dedupe(ohlc, vol)
                return {"ohlc": ohlc, "volume": vol}

            # —— FALLBACK if view empty —— #
            num, unit      = _parse_timeframe(timeframe)
            period_ms      = UNIT_MS[unit] * num
            minutes_needed = period_ms // UNIT_MS["m"]
            raw_limit      = None if limit is None else limit * minutes_needed

            fb = await self.fetch_ohlcv(
                symbol, "1m", since=since, before=before, limit=raw_limit
            )
            raw = [
                {"timestamp": o[0], "open": o[1], "high": o[2],
                 "low":       o[3], "close": o[4], "volume": v[1]}
                for o, v in zip(fb["ohlc"], fb["volume"])
            ]
            bars = _resample(raw, timeframe)
            ohlc = [[b["timestamp"], b["open"], b["high"],
                     b["low"],       b["close"]] for b in bars]
            vol  = [[b["timestamp"], b["volume"]] for b in bars]
            ohlc, vol = _dedupe(ohlc, vol)
            return {"ohlc": ohlc, "volume": vol}


        # —— pure-fallback (no continuous-agg view) —— #
        num, unit      = _parse_timeframe(timeframe)
        period_ms      = UNIT_MS[unit] * num
        minutes_needed = period_ms // UNIT_MS["m"]
        raw_limit      = None if limit is None else limit * minutes_needed

        fb = await self.fetch_ohlcv(
            symbol, "1m", since=since, before=before, limit=raw_limit
        )
        raw = [
            {"timestamp": o[0], "open": o[1], "high": o[2],
             "low":       o[3], "close": o[4], "volume": v[1]}
            for o, v in zip(fb["ohlc"], fb["volume"])
        ]
        bars = _resample(raw, timeframe)
        ohlc = [[b["timestamp"], b["open"], b["high"],
                 b["low"],       b["close"]] for b in bars]
        vol  = [[b["timestamp"], b["volume"]] for b in bars]
        ohlc, vol = _dedupe(ohlc, vol)
        return {"ohlc": ohlc, "volume": vol}


    async def fetch_latest_bar(
        self,
        symbol:    str,
        timeframe: str
    ) -> Optional[Dict[str, Any]]:
        """
        Always fetch fresh from plugin or DB first, then cache and return.
        """
        cache     = current_app.config.get("CACHE")
        cache_key = f"latest:ohlcv:{self.market}:{self.provider}:{symbol}:{timeframe}"
        bar: Optional[Dict[str, Any]] = None

        # 1) Try plugin/DB for the true latest bar
        try:
            if timeframe == "1m":
                bar = await self.plugin.fetch_latest_ohlcv(self.provider, symbol, "1m")
            else:
                num, _ = _parse_timeframe(timeframe)
                raw = await self.plugin.fetch_historical_ohlcv(
                    self.provider, symbol, "1m", limit=num
                )
                if len(raw) >= num:
                    res = _resample(raw, timeframe)
                    bar = res[-1] if res else None
                else:
                    logger.warning("Not enough 1m bars for %s %s", symbol, timeframe)
        except Exception as e:
            logger.error("Plugin error in fetch_latest_bar: %s", e)

        # 2) Fallback to DB if the plugin gave us nothing
        if bar is None:
            try:
                rows = await fetch_query(
                    "SELECT timestamp, open, high, low, close, volume "
                    "FROM ohlcv_data "
                    "WHERE market=$1 AND provider=$2 AND symbol=$3 AND timeframe=$4 "
                    "ORDER BY timestamp DESC LIMIT 1",
                    self.market, self.provider, symbol, timeframe
                )
                if rows:
                    r  = rows[0]
                    ts = int(r["timestamp"].timestamp() * 1000)
                    bar = {
                        "timestamp": ts,
                        "open":      r["open"],
                        "high":      r["high"],
                        "low":       r["low"],
                        "close":     r["close"],
                        "volume":    r["volume"],
                    }
            except Exception as e:
                logger.error("DB fallback error in fetch_latest_bar: %s", e)

        # 3) Cache and return
        if cache and bar:
            try:
                await cache.set(cache_key, bar, expire=3600)
            except Exception as e:
                logger.error("Redis set error (latest_bar): %s", e)

        return bar
