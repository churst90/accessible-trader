# plugins/base.py

import abc
from typing import Any, Callable, Coroutine, Dict, List, Optional

class PluginError(Exception):
    """Base exception for all plugin-related errors."""
    pass


class PluginFeatureNotSupportedError(NotImplementedError, PluginError):
    """
    Raised when a plugin does not support a requested feature.

    Attributes:
        plugin_name (str): The name of the plugin.
        feature_name (str): The name of the unsupported feature.
    """
    def __init__(self, plugin_name: str, feature_name: str):
        self.plugin_name = plugin_name
        self.feature_name = feature_name
        super().__init__(f"Plugin '{plugin_name}' does not support feature: '{feature_name}'")


class MarketPlugin(abc.ABC):
    """
    Abstract base class for market data plugins.

    Plugins provide access to market data (e.g., OHLCV bars) and optionally support real-time ticks
    or trading capabilities. Subclasses must implement core data fetching methods and define
    `plugin_key` and `supported_markets`.

    Attributes:
        plugin_key (Optional[str]): Unique identifier for the plugin (e.g., "crypto", "alpaca").
        supported_markets (List[str]): List of supported market types (e.g., ["crypto"], ["stocks"]).
    """
    plugin_key: Optional[str] = None
    supported_markets: List[str] = []

    def __init__(self):
        """Initialize the plugin and validate required class attributes."""
        if not self.plugin_key:
            raise ValueError(f"Plugin {self.__class__.__name__} must define a non-empty plugin_key")
        if not self.supported_markets:
            raise ValueError(f"Plugin {self.__class__.__name__} must define non-empty supported_markets")

    # --- Core Data Fetching Methods (Mandatory) ---

    @abc.abstractmethod
    async def get_exchanges(self) -> List[str]:
        """
        Return a list of supported provider identifiers for this plugin.

        For crypto plugins, this returns exchange IDs (e.g., ["binance", "coinbasepro"]).
        For stocks plugins, this might return a single provider (e.g., ["alpaca"]).

        Returns:
            List[str]: List of provider identifiers.

        Raises:
            PluginError: If the operation fails.
        """
        pass

    @abc.abstractmethod
    async def get_symbols(self, provider: str) -> List[str]:
        """
        Return a list of tradable symbols for the given provider.

        Args:
            provider (str): Provider identifier (e.g., "binance", "alpaca").

        Returns:
            List[str]: List of symbol identifiers (e.g., ["BTC/USD", "ETH/USD"]).

        Raises:
            PluginError: If the provider is invalid or the operation fails.
        """
        pass

    @abc.abstractmethod
    async def fetch_historical_ohlcv(
        self,
        provider: str,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical OHLCV bars for the given provider, symbol, and timeframe.

        Args:
            provider (str): Provider identifier (e.g., "binance", "alpaca").
            symbol (str): Trading pair symbol (e.g., "BTC/USD").
            timeframe (str): Timeframe string (e.g., "1m", "5m").
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            limit (Optional[int]): Maximum number of bars to return.
            params (Optional[Dict[str, Any]]): Extra parameters for the underlying API.

        Returns:
            List[Dict[str, Any]]: List of OHLCV bars, each with keys:
                - timestamp (int): Milliseconds since epoch.
                - open (float): Opening price.
                - high (float): Highest price.
                - low (float): Lowest price.
                - close (float): Closing price.
                - volume (float): Trading volume.
            Bars are sorted by timestamp ascending (oldest first).

        Raises:
            PluginError: If the provider, symbol, or timeframe is invalid or the fetch fails.
        """
        pass

    @abc.abstractmethod
    async def fetch_latest_ohlcv(
        self,
        provider: str,
        symbol: str,
        timeframe: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch the most recent OHLCV bar for the given provider, symbol, and timeframe.

        Args:
            provider (str): Provider identifier (e.g., "binance", "alpaca").
            symbol (str): Trading pair symbol (e.g., "BTC/USD").
            timeframe (str): Timeframe string (e.g., "1m", "5m").

        Returns:
            Optional[Dict[str, Any]]: A single OHLCV bar with keys:
                - timestamp (int): Milliseconds since epoch.
                - open (float): Opening price.
                - high (float): Highest price.
                - low (float): Lowest price.
                - close (float): Closing price.
                - volume (float): Trading volume.
            Returns None if no bar is available.

        Raises:
            PluginError: If the provider, symbol, or timeframe is invalid or the fetch fails.
        """
        pass

    # --- Optional Real-Time Data Methods ---

    async def watch_ticks(
        self,
        provider: str,
        symbol: str,
        callback: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """
        Subscribe to real-time tick data for the given provider and symbol.

        Args:
            provider (str): Provider identifier.
            symbol (str): Trading pair symbol.
            callback (Callable): Async callback to handle tick data.

        Raises:
            PluginFeatureNotSupportedError: If the plugin does not support real-time ticks.
        """
        raise PluginFeatureNotSupportedError(self.__class__.__name__, "watch_ticks")

    # --- Optional Historical Trades Method ---

    async def fetch_trades(
        self,
        provider: str,
        symbol: str,
        since: Optional[int] = None,
        limit: Optional[int] = 100,
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical trade data for the given provider and symbol.

        Args:
            provider (str): Provider identifier.
            symbol (str): Trading pair symbol.
            since (Optional[int]): Start timestamp in milliseconds.
            limit (Optional[int]): Maximum number of trades to return (default: 100).

        Returns:
            List[Dict[str, Any]]: List of trade records.

        Raises:
            PluginFeatureNotSupportedError: If the plugin does not support trade fetching.
        """
        raise PluginFeatureNotSupportedError(self.__class__.__name__, "fetch_trades")

    # --- Optional Trading Methods ---

    async def get_trade_client(
        self,
        user_api_key: str,
        user_api_secret: str,
        user_api_passphrase: Optional[str] = None,
        is_testnet: bool = False,
        **kwargs: Any,
    ) -> Any:
        """
        Initialize a trading client for the plugin.

        Args:
            user_api_key (str): User's API key.
            user_api_secret (str): User's API secret.
            user_api_passphrase (Optional[str]): API passphrase (if required).
            is_testnet (bool): Whether to use testnet (default: False).
            **kwargs: Additional provider-specific parameters.

        Returns:
            Any: A trading client instance.

        Raises:
            PluginFeatureNotSupportedError: If the plugin does not support trading.
        """
        raise PluginFeatureNotSupportedError(self.__class__.__name__, "get_trade_client (trading)")

    async def place_order(
        self,
        trade_client: Any,
        provider: str,
        symbol: str,
        order_type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Place a trading order using the provided trading client.

        Args:
            trade_client (Any): The trading client instance.
            provider (str): Provider identifier.
            symbol (str): Trading pair symbol.
            order_type (str): Order type (e.g., "market", "limit").
            side (str): Order side ("buy" or "sell").
            amount (float): Order amount.
            price (Optional[float]): Order price for limit orders.
            params (Optional[Dict[str, Any]]): Additional order parameters.

        Returns:
            Dict[str, Any]: Order details.

        Raises:
            PluginFeatureNotSupportedError: If the plugin does not support trading.
        """
        raise PluginFeatureNotSupportedError(self.__class__.__name__, "place_order (trading)")

    async def fetch_balance(
        self,
        trade_client: Any,
        provider: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Fetch account balance using the provided trading client.

        Args:
            trade_client (Any): The trading client instance.
            provider (str): Provider identifier.
            params (Optional[Dict[str, Any]]): Additional parameters.

        Returns:
            Dict[str, Any]: Balance details.

        Raises:
            PluginFeatureNotSupportedError: If the plugin does not support trading.
        """
        raise PluginFeatureNotSupportedError(self.__class__.__name__, "fetch_balance (trading)")

    async def fetch_open_orders(
        self,
        trade_client: Any,
        provider: str,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch open orders using the provided trading client.

        Args:
            trade_client (Any): The trading client instance.
            provider (str): Provider identifier.
            symbol (Optional[str]): Trading pair symbol.
            since (Optional[int]): Start timestamp in milliseconds.
            limit (Optional[int]): Maximum number of orders to return.
            params (Optional[Dict[str, Any]]): Additional parameters.

        Returns:
            List[Dict[str, Any]]: List of open order details.

        Raises:
            PluginFeatureNotSupportedError: If the plugin does not support trading.
        """
        raise PluginFeatureNotSupportedError(self.__class__.__name__, "fetch_open_orders (trading)")

    # --- Utility Methods ---

    async def get_supported_features(self) -> Dict[str, bool]:
        """
        Return a dictionary indicating which optional features are supported.

        Returns:
            Dict[str, bool]: Dictionary with feature names and their support status:
                - watch_ticks: Real-time tick data support.
                - fetch_trades: Historical trade data support.
                - trading_api: Trading API support.
        """
        return {
            "watch_ticks": False,
            "fetch_trades": False,
            "trading_api": False,
        }

    async def supported_timeframes(self, provider: str, symbol: str) -> List[str]:
        """
        Return a list of supported timeframes for the given provider and symbol.

        Args:
            provider (str): Provider identifier (e.g., "binance", "alpaca").
            symbol (str): Trading pair symbol (e.g., "BTC/USD").

        Returns:
            List[str]: List of supported timeframe strings (e.g., ["1m", "5m", "1h"]).
            Defaults to ["1m"] if not overridden.

        Raises:
            PluginError: If the provider or symbol is invalid.
        """
        return ["1m"]

    @abc.abstractmethod
    async def close(self) -> None:
        """
        Clean up resources used by the plugin (e.g., close API connections).

        Raises:
            PluginError: If the cleanup fails.
        """
        pass