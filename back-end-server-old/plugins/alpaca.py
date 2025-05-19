# plugins/alpaca.py

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp
from plugins.base import MarketPlugin, PluginError
from utils.timeframes import TIMEFRAME_PATTERN, UNIT_MS

logger = logging.getLogger("AlpacaPlugin")


class AlpacaPlugin(MarketPlugin):
    supported_markets = ["stocks"]

    def __init__(self, api_key: str, api_secret: str):
        if not api_key or not api_secret:
            raise PluginError("Alpaca API key & secret must be provided")
        self.api_key = api_key
        self.api_secret = api_secret

        self.trading_base = "https://paper-api.alpaca.markets/v2"
        self.data_base    = "https://data.alpaca.markets/v2"

        self._session_trading = None
        self._session_data    = None

    async def _get_trading_session(self) -> aiohttp.ClientSession:
        if not self._session_trading or self._session_trading.closed:
            headers = {
                "APCA-API-KEY-ID":     self.api_key,
                "APCA-API-SECRET-KEY": self.api_secret,
            }
            self._session_trading = aiohttp.ClientSession(headers=headers)
        return self._session_trading

    async def _get_data_session(self) -> aiohttp.ClientSession:
        if not self._session_data or self._session_data.closed:
            headers = {
                "APCA-API-KEY-ID":     self.api_key,
                "APCA-API-SECRET-KEY": self.api_secret,
            }
            self._session_data = aiohttp.ClientSession(headers=headers)
        return self._session_data

    async def get_exchanges(self) -> List[str]:
        return ["alpaca"]

    async def get_symbols(self, exchange: str) -> List[str]:
        sess = await self._get_trading_session()
        url  = f"{self.trading_base}/assets"
        params = {"status": "active", "asset_class": "us_equity"}

        async with sess.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise PluginError(f"Alpaca assets error {resp.status}: {text}")
            data = await resp.json()

        return [asset["symbol"] for asset in data]

    async def fetch_latest_ohlcv(self, exchange: str, symbol: str, timeframe: str) -> Dict[str, Any]:
        bars = await self.fetch_historical_ohlcv(exchange, symbol, "1m", limit=1)
        if not bars:
            raise PluginError("No data returned for latest OHLCV.")
        return bars[-1]

    async def fetch_historical_ohlcv(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None,
        before: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        # Always fetch 1m candles
        sess = await self._get_data_session()
        url  = f"{self.data_base}/stocks/bars"

        params: Dict[str, Any] = {
            "symbols":   symbol,
            "timeframe": "1Min",
            "limit":     limit
        }
        if since:
            params["start"] = datetime.fromtimestamp(since / 1000, tz=timezone.utc).isoformat()
        if before:
            params["end"]   = datetime.fromtimestamp(before / 1000, tz=timezone.utc).isoformat()

        async with sess.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise PluginError(f"Alpaca bars error {resp.status}: {text}")
            payload = await resp.json()

        bars = payload.get("bars", {}).get(symbol, [])
        one_minute_bars = [
            {
                "timestamp": int(datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp() * 1000),
                "open":      b["o"],
                "high":      b["h"],
                "low":       b["l"],
                "close":     b["c"],
                "volume":    b["v"],
            }
            for b in bars
        ]

        # Resample if needed
        if timeframe == "1m":
            return one_minute_bars
        else:
            return self._resample(one_minute_bars, timeframe)

    def _resample(self, raw: List[Dict[str, Any]], tf: str) -> List[Dict[str, Any]]:
        match = TIMEFRAME_PATTERN.match(tf)
        if not match:
            raise PluginError(f"Invalid timeframe '{tf}' for resampling.")
        num, unit = int(match.group(1)), match.group(2)
        period = UNIT_MS[unit] * num

        buckets: Dict[int, Dict[str, Any]] = {}
        for bar in raw:
            ts = bar["timestamp"]
            start = ts - (ts % period)
            if start not in buckets:
                buckets[start] = dict(bar)
            else:
                b = buckets[start]
                b["high"]   = max(b["high"], bar["high"])
                b["low"]    = min(b["low"],  bar["low"])
                b["close"]  = bar["close"]
                b["volume"] += bar["volume"]

        return [{"timestamp": s, **buckets[s]} for s in sorted(buckets)]

    async def fetch_trades(self, *args, **kwargs):
        raise PluginError("fetch_trades not supported for Alpaca free data")

    async def watch_trades(self, *args, **kwargs):
        raise PluginError("watch_trades not supported for Alpaca free data")

    async def close(self) -> None:
        if self._session_trading and not self._session_trading.closed:
            await self._session_trading.close()
        if self._session_data    and not self._session_data.closed:
            await self._session_data.close()
        logger.info("Alpaca HTTP sessions closed")
