# plugins/crypto.py

import asyncio
import logging
import ccxt.async_support as ccxt
from ccxt.base.errors import NetworkError, ExchangeError, RateLimitExceeded
from typing import Any, Callable, Dict, List, Optional

from plugins.base import MarketPlugin, PluginError

logger = logging.getLogger("CryptoPlugin")

class CryptoPlugin(MarketPlugin):
    supported_markets = ["crypto"]

    def __init__(self):
        self._instances: Dict[str, ccxt.Exchange] = {}
        self._supported_exchanges = set(ccxt.exchanges)

    async def get_exchanges(self) -> List[str]:
        return list(self._supported_exchanges)

    async def get_symbols(self, exchange: str) -> List[str]:
        ex = self._get_exchange_instance(exchange)
        try:
            markets = await self._with_retries(ex.load_markets)
            # --- NEW: Filter out any symbol containing ":" ---
            symbols = [symbol for symbol in markets.keys() if ":" not in symbol]
            return symbols
        except Exception as e:
            logger.error(f"Error loading markets for {exchange}: {e}", exc_info=True)
            raise PluginError(f"Failed to get symbols for {exchange}: {e}") from e

    async def fetch_latest_ohlcv(self, exchange: str, symbol: str, timeframe: str) -> Dict[str, Any]:
        bars = await self.fetch_historical_ohlcv(exchange, symbol, timeframe, limit=1)
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
        limit: Optional[int] = 100
    ) -> List[Dict[str, Any]]:
        ex = self._get_exchange_instance(exchange)
        try:
            raw_data = await self._with_retries(
                ex.fetch_ohlcv, symbol, timeframe, since, limit
            )
            if before:
                raw_data = [bar for bar in raw_data if bar[0] < before]
            return [
                {
                    "timestamp": bar[0],
                    "open":      bar[1],
                    "high":      bar[2],
                    "low":       bar[3],
                    "close":     bar[4],
                    "volume":    bar[5],
                }
                for bar in raw_data
            ]
        except Exception as e:
            logger.error(f"fetch_historical_ohlcv error for {exchange} {symbol}: {e}", exc_info=True)
            raise PluginError(f"Failed to fetch OHLCV from {exchange} for {symbol}: {e}") from e

    async def fetch_trades(self, exchange: str, symbol: str, since: Optional[int] = None, limit: int = 500) -> List[Dict[str, Any]]:
        ex = self._get_exchange_instance(exchange)
        try:
            data = await self._with_retries(ex.fetch_trades, symbol, since, limit)
            return [
                {"id": t["id"], "timestamp": t["timestamp"], "price": t["price"], "amount": t["amount"]}
                for t in data
            ]
        except Exception as e:
            logger.error(f"fetch_trades error for {exchange} {symbol}: {e}", exc_info=True)
            raise PluginError(f"Failed to fetch trades from {exchange}: {e}") from e

    async def watch_trades(self, exchange: str, symbol: str, callback: Callable[[Dict[str, Any]], Any]) -> None:
        ex = self._get_exchange_instance(exchange)
        try:
            last_ts = None
            while True:
                trades = await self.fetch_trades(exchange, symbol, since=last_ts)
                for t in trades:
                    await callback(t)
                    last_ts = t["timestamp"]
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info(f"watch_trades cancelled for {exchange}/{symbol}")
        except Exception as e:
            logger.error(f"watch_trades error for {exchange} {symbol}: {e}", exc_info=True)
            raise PluginError(f"Failed to watch trades for {exchange}/{symbol}: {e}") from e

    async def close(self) -> None:
        for name, ex in list(self._instances.items()):
            try:
                await ex.close()
                logger.info(f"Closed exchange instance {name}")
            except Exception as e:
                logger.error(f"Error closing exchange {name}: {e}", exc_info=True)
            finally:
                del self._instances[name]

    def _get_exchange_instance(self, exchange: str) -> ccxt.Exchange:
        exchange = exchange.lower()
        if exchange not in self._supported_exchanges:
            raise PluginError(f"Unsupported exchange: {exchange}")

        if exchange not in self._instances:
            try:
                cls = getattr(ccxt, exchange)
                self._instances[exchange] = cls({"enableRateLimit": True})
            except AttributeError as e:
                logger.error(f"Failed to init exchange '{exchange}': {e}", exc_info=True)
                raise PluginError(f"Failed to init exchange '{exchange}': {e}") from e

        return self._instances[exchange]

    async def _with_retries(self, fn: Callable, *args, retries: int = 3, delay: float = 1.0, **kwargs):
        for attempt in range(1, retries + 1):
            try:
                return await fn(*args, **kwargs)
            except (NetworkError, ExchangeError, RateLimitExceeded) as e:
                logger.warning(f"Retry {attempt}/{retries} for {fn.__name__} after error: {e}")
                if attempt == retries:
                    logger.error(f"Max retries reached for {fn.__name__}", exc_info=True)
                    raise
                await asyncio.sleep(delay)
