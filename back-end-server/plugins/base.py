# plugins/base.py

import abc
from typing import Any, Callable, List, Dict, Optional


class PluginError(Exception):
    """Base exception for all plugin-related errors."""
    pass


class MarketPlugin(abc.ABC):
    """
    Abstract base class for all market data plugins.
    All plugins must implement these methods.
    """

    @abc.abstractmethod
    async def get_exchanges(self) -> List[str]:
        """
        Return a list of supported exchange identifiers.
        """
        pass

    @abc.abstractmethod
    async def get_symbols(self, exchange: str) -> List[str]:
        """
        Return a list of tradable symbols for the given exchange.
        :param exchange: Exchange identifier
        """
        pass

    @abc.abstractmethod
    async def fetch_latest_ohlcv(
        self,
        exchange: str,
        symbol: str,
        timeframe: str
    ) -> Dict[str, Any]:
        """
        Fetch the most recent OHLCV bar for the given symbol and timeframe.
        Used for real-time updates.
        """
        pass

    @abc.abstractmethod
    async def fetch_historical_ohlcv(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None,
        before: Optional[int] = None,
        limit: Optional[int] = 100
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars over a time range.

        :param exchange: Exchange identifier
        :param symbol: Trading pair symbol
        :param timeframe: Timeframe string, e.g. "1m", "5m", "1h"
        :param since: (optional) Start timestamp (ms)
        :param before: (optional) End timestamp (ms)
        :param limit: (optional) Max number of bars to return
        """
        pass

    @abc.abstractmethod
    async def fetch_trades(
        self,
        exchange: str,
        symbol: str,
        since: Optional[int] = None,
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent trades for the given symbol.

        :param exchange: Exchange identifier
        :param symbol: Trading pair symbol
        :param since: Earliest timestamp (ms) for filtering trades
        :param limit: Max number of trades to retrieve
        """
        pass

    @abc.abstractmethod
    async def watch_trades(
        self,
        exchange: str,
        symbol: str,
        callback: Callable[[Dict[str, Any]], Any]
    ) -> None:
        """
        Subscribe to real-time trades and call the callback function per trade.

        :param exchange: Exchange identifier
        :param symbol: Trading pair symbol
        :param callback: Callable that processes each new trade dict
        """
        pass

    @abc.abstractmethod
    async def close(self) -> None:
        """
        Clean up and close any open connections or background tasks.
        """
        pass
