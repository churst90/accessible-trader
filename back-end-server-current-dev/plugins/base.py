# plugins/base.py

import abc
import logging
from typing import Any, Dict, List, Optional, TypedDict, Type

# Initialize a logger for this module
logger = logging.getLogger(__name__)

# --- Custom Plugin Exceptions ---

class PluginError(Exception):
    """
    Base exception for all plugin-related errors.

    Attributes:
        message (str): The error message.
        provider_id (Optional[str]): The ID of the provider that caused the error.
        original_exception (Optional[Exception]): The original exception, if any, that was caught.
    """
    def __init__(self, message: str, provider_id: Optional[str] = None, original_exception: Optional[Exception] = None):
        self.provider_id = provider_id
        self.original_exception = original_exception
        
        full_message = f"Plugin error"
        if provider_id:
            full_message += f" for provider '{provider_id}'"
        full_message += f": {message}"
        
        if original_exception:
            # Avoid overly verbose original exception strings
            orig_exc_str = str(original_exception)
            if len(orig_exc_str) > 150: # Arbitrary limit for brevity
                orig_exc_str = orig_exc_str[:150] + "..."
            full_message += f" (Original: {type(original_exception).__name__}: {orig_exc_str})"
            
        super().__init__(full_message)

class PluginFeatureNotSupportedError(NotImplementedError, PluginError):
    """
    Raised when a plugin instance does not support a requested feature for its configured provider.

    Attributes:
        plugin_key (str): The key of the plugin class.
        feature_name (str): The name of the unsupported feature.
        # provider_id is inherited from PluginError
    """
    def __init__(self, plugin_key: str, provider_id: str, feature_name: str):
        self.plugin_key = plugin_key
        self.feature_name = feature_name
        super().__init__(
            message=f"Feature '{feature_name}' not supported by plugin class '{plugin_key}'.",
            provider_id=provider_id
        )

class AuthenticationPluginError(PluginError):
    """Raised for authentication-specific errors with a plugin/provider."""
    def __init__(self, provider_id: str, message: str = "Authentication failed.", original_exception: Optional[Exception] = None):
        super().__init__(message=message, provider_id=provider_id, original_exception=original_exception)

class NetworkPluginError(PluginError):
    """Raised for network-related errors (timeouts, connection issues) with a plugin/provider."""
    def __init__(self, provider_id: str, message: str = "Network error.", original_exception: Optional[Exception] = None):
        super().__init__(message=message, provider_id=provider_id, original_exception=original_exception)

# --- Data Structures ---

class OHLCVBar(TypedDict):
    """
    Represents a single OHLCV (Open, High, Low, Close, Volume) data bar.
    All timestamps are millisecond UTC epochs.
    """
    timestamp: int  # Milliseconds since epoch, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float

# --- Abstract Base Class for Market Plugins ---

class MarketPlugin(abc.ABC):
    """
    Abstract base class for market data plugins.

    Each plugin *class* is identified by a unique `plugin_key` (e.g., "crypto", "alpaca")
    and declares the `supported_markets` (e.g., ["crypto"], ["stocks"]) it can serve.
    It must also provide a way to list all `provider_id`s it can be configured to handle
    via the `list_configurable_providers` class method.

    An *instance* of a plugin is configured for a specific `provider_id` (e.g.,
    "binance" for a CryptoPlugin instance, or "alpaca" for an AlpacaPlugin instance).
    This instance can be further configured with API credentials and testnet status.
    The lifecycle of plugin instances (creation, caching, closing) is managed by
    services like `MarketService`.
    """
    plugin_key: str = ""  # MANDATORY: Concrete subclasses MUST override this.
    supported_markets: List[str] = []  # MANDATORY: Concrete subclasses SHOULD override.

    def __init__(
        self,
        provider_id: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        is_testnet: bool = False,
        request_timeout: int = 30000,
        verbose_logging: bool = False,
        **kwargs: Any
    ):
        """
        Initializes the MarketPlugin instance.

        Args:
            provider_id (str): The specific provider this instance is configured for (e.g., "binance", "alpaca").
                               This is crucial for multi-provider plugins like CryptoPlugin.
            api_key (Optional[str]): User's API key for authentication, if applicable.
            api_secret (Optional[str]): User's API secret for authentication, if applicable.
            api_passphrase (Optional[str]): User's API passphrase for authentication, if applicable.
            is_testnet (bool): Flag indicating if testnet/sandbox environment should be used.
            request_timeout (int): Default request timeout in milliseconds for API calls.
            verbose_logging (bool): Flag to enable more verbose internal logging for the plugin.
            **kwargs: Catches any other arguments passed, allowing for future plugin-specific configurations.
        """
        if not self.__class__.plugin_key: # Ensure the class attribute is set
            raise ValueError(f"Plugin class '{self.__class__.__name__}' must define a non-empty 'plugin_key' attribute.")
        if not provider_id:
            raise ValueError(f"Plugin instance '{self.__class__.__name__}' must be initialized with a 'provider_id'.")

        self.provider_id: str = provider_id.lower() # Normalize provider_id for the instance.
        self.api_key: Optional[str] = api_key
        self.api_secret: Optional[str] = api_secret
        self.api_passphrase: Optional[str] = api_passphrase
        self.is_testnet: bool = is_testnet
        self.request_timeout: int = request_timeout
        self.verbose_logging: bool = verbose_logging
        self.additional_kwargs: Dict[str, Any] = kwargs # Store for plugin-specific use

        logger.debug(
            f"Initialized {self.__class__.__name__} (plugin_class_key: {self.__class__.plugin_key}) for provider_id '{self.provider_id}'. "
            f"Testnet: {self.is_testnet}, API Key Provided: {bool(self.api_key)}"
        )

    # --- Class Methods for Plugin Discovery and Capabilities ---

    @classmethod
    def get_plugin_key(cls) -> str:
        """Returns the unique key for this plugin type, defined by the class attribute `plugin_key`."""
        if not cls.plugin_key:
            raise NotImplementedError(f"Plugin class {cls.__name__} must define a 'plugin_key' attribute.")
        return cls.plugin_key

    @classmethod
    def get_supported_markets(cls) -> List[str]:
        """Returns a list of market identifiers (e.g., 'crypto', 'stocks') this plugin CLASS supports."""
        if not isinstance(cls.supported_markets, list):
             logger.warning(f"Plugin class {cls.__name__} 'supported_markets' is not a list. Defaulting to empty.")
             return []
        return cls.supported_markets

    @classmethod
    @abc.abstractmethod
    def list_configurable_providers(cls) -> List[str]:
        """
        Returns a list of unique provider_ids that this plugin CLASS can be
        instantiated to handle.
        For a multi-provider plugin like CryptoPlugin, this would list all supported CCXT exchanges.
        For a single-provider plugin like AlpacaPlugin, this would typically return ['alpaca'].
        """
        pass

    # --- Core Data Fetching Abstract Methods (to be implemented by subclasses) ---

    @abc.abstractmethod
    async def get_symbols(self) -> List[str]:
        """
        Return a list of tradable symbols for this plugin's configured `provider_id`.
        Example: For a Binance instance, ["BTC/USDT", "ETH/USDT", ...].
                 For an Alpaca instance, ["AAPL", "MSFT", ...].

        Returns:
            List[str]: A list of symbol identifiers.

        Raises:
            PluginError: If the operation fails (e.g., network issue, API error).
            AuthenticationPluginError: If authentication is required for this operation and fails.
        """
        pass

    @abc.abstractmethod
    async def fetch_historical_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[OHLCVBar]:
        """
        Fetch historical OHLCV bars for the given symbol and timeframe from the
        plugin's configured `provider_id`.

        Args:
            symbol (str): Trading pair symbol (e.g., "BTC/USD", "AAPL").
            timeframe (str): Timeframe string (e.g., "1m", "5m", "1D").
                             Plugins should normalize or document the expected format.
            since (Optional[int]): Start timestamp in milliseconds (inclusive, UTC).
            limit (Optional[int]): Maximum number of bars to return.
            params (Optional[Dict[str, Any]]): Extra provider-specific parameters for the API call.
                                               This can be used for things like 'until' timestamps if the API
                                               supports it, or other custom flags.

        Returns:
            List[OHLCVBar]: A list of OHLCV bars, sorted by timestamp in ascending order.
                            Returns an empty list if no data is available for the requested range.

        Raises:
            PluginError: For general plugin or API errors.
            AuthenticationPluginError: If authentication fails.
            NetworkPluginError: For network-related issues.
            ValueError: For invalid input parameters if not caught by the plugin.
        """
        pass

    @abc.abstractmethod
    async def fetch_latest_ohlcv(
        self,
        symbol: str,
        timeframe: str, # Typically the most granular, e.g., "1m"
    ) -> Optional[OHLCVBar]:
        """
        Fetch the most recent OHLCV bar for the given symbol and timeframe from the
        plugin's configured `provider_id`.

        Args:
            symbol (str): Trading pair symbol.
            timeframe (str): Timeframe string (e.g., "1m"). It's often advisable for implementations
                             to fetch the most granular data (e.g., 1m) regardless of the requested
                             timeframe if the goal is the absolute "latest" tick or bar.

        Returns:
            Optional[OHLCVBar]: A single OHLCV bar, or None if no bar is available.

        Raises:
            PluginError: For general plugin or API errors. Implementations might choose to return None
                         on non-critical errors like "no data available."
            AuthenticationPluginError: If authentication fails.
            NetworkPluginError: For network-related issues.
        """
        pass

    # --- Optional Utility / Metadata Methods (subclasses should override if applicable) ---

    async def get_market_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetch detailed market information for a specific symbol (e.g., precision, limits, fees).
        This is an optional method.

        Args:
            symbol (str): Trading pair symbol.

        Returns:
            Optional[Dict[str, Any]]: A dictionary containing market metadata,
                                     or None if not available or not supported.

        Raises:
            PluginFeatureNotSupportedError: If the plugin does not support this feature.
            PluginError: For other errors during fetching.
            AuthenticationPluginError: If authentication is required and fails.
        """
        logger.debug(f"get_market_info not implemented by {self.__class__.__name__} for provider '{self.provider_id}'.")
        raise PluginFeatureNotSupportedError(self.__class__.plugin_key, self.provider_id, "get_market_info")

    async def validate_symbol(self, symbol: str) -> bool:
        """
        Validate whether the given symbol is valid and active for the configured `provider_id`.
        The default implementation attempts to use `get_market_info`.
        Subclasses should override for more efficient or provider-specific validation if possible.

        Args:
            symbol (str): Trading pair symbol.

        Returns:
            bool: True if the symbol is considered valid and active, False otherwise.
                  Should generally return False on error or if not found, rather than raising.
        """
        try:
            info = await self.get_market_info(symbol)
            if info is None: # Market info not found or not supported
                return False
            # A common convention: if 'active' key exists, its value determines activity.
            # If 'active' key doesn't exist, but we got info, assume it's active/valid.
            is_active = info.get('active', True)
            return is_active
        except PluginFeatureNotSupportedError:
            logger.warning(
                f"validate_symbol cannot use get_market_info for {self.__class__.plugin_key} provider '{self.provider_id}' (feature not supported). "
                "This symbol cannot be validated by the default mechanism. Consider overriding validate_symbol in the plugin."
            )
            return False # Cannot validate, assume False for safety
        except PluginError as e:
            logger.warning(f"validate_symbol for '{symbol}' on '{self.provider_id}' failed due to PluginError: {e}. Assuming invalid.")
            return False
        except Exception:
            logger.exception(f"Unexpected error during validate_symbol for '{symbol}' on '{self.provider_id}'. Assuming invalid.")
            return False

    async def get_supported_timeframes(self) -> Optional[List[str]]:
        """
        Return a list of timeframes natively supported by this plugin's configured `provider_id`.
        This information is often provider-wide but can sometimes be market-specific.

        Returns:
            Optional[List[str]]: A list of supported timeframe strings (e.g., ["1m", "5m", "1h"]),
                                 or None if this information is not explicitly provided by the plugin.
                                 An empty list could also indicate no specific timeframes known other than defaults.
        """
        logger.warning(
            f"Plugin {self.__class__.__name__} for provider '{self.provider_id}' "
            f"does not explicitly implement get_supported_timeframes. Defaulting to None."
        )
        return None

    async def get_fetch_ohlcv_limit(self) -> int:
        """
        Return the maximum number of OHLCV bars that can typically be fetched in a single API request
        from this plugin's configured `provider_id`.

        Returns:
            int: Maximum number of bars. Defaults to a common safe value if not overridden.
        """
        default_limit = 1000 # A common safe default for many exchanges
        logger.warning(
            f"Plugin {self.__class__.__name__} for provider '{self.provider_id}' "
            f"does not explicitly implement get_fetch_ohlcv_limit. Defaulting to {default_limit}."
        )
        return default_limit

    async def get_supported_features(self) -> Dict[str, bool]:
        """
        Return a dictionary indicating which optional features are supported by this plugin instance.
        This can be dynamic based on the `provider_id` or API key permissions.
        Subclasses should override to accurately reflect their capabilities.

        Standard feature keys:
            - "watch_ticks": bool (Real-time tick data stream support)
            - "fetch_trades": bool (Historical public trade data support)
            - "trading_api": bool (Support for placing/managing orders, fetching balance etc.)
            - "get_market_info": bool (Support for `get_market_info` method)
            - "validate_symbol": bool (Support for `validate_symbol` method beyond default)
            - "get_supported_timeframes": bool (Support for `get_supported_timeframes` method)
            - "get_fetch_ohlcv_limit": bool (Support for `get_fetch_ohlcv_limit` method beyond default)
        """
        return {
            "watch_ticks": False,
            "fetch_trades": False,
            "trading_api": False,
            "get_market_info": False, # Default to False, override if implemented
            "validate_symbol": False, # Default to False (meaning default impl. is used), override if specific validation
            "get_supported_timeframes": False, # Default to False, override if plugin can list them
            "get_fetch_ohlcv_limit": False, # Default to False, override if plugin knows its limit
        }

    # --- Lifecycle Method (Mandatory for subclasses to implement) ---

    @abc.abstractmethod
    async def close(self) -> None:
        """
        Clean up any resources used by this plugin instance.
        This typically includes closing network sessions or connections.
        This method is called by services like `MarketService` when the plugin instance
        is no longer needed (e.g., due to cache eviction or application shutdown).
        Implementations should be idempotent (safe to call multiple times).

        Raises:
            PluginError: If a significant error occurs during the closure process.
        """
        pass