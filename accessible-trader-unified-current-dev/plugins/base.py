# plugins/base.py

import abc
import logging
import time # For fetch_exchange_time fallback
from typing import Any, Dict, List, Optional, TypedDict, Type, Callable, Awaitable, Tuple

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
    open: float #
    high: float #
    low: float #
    close: float #
    volume: float #

class Order(TypedDict, total=False):
    """
    Represents a trading order. Fields depend on the exchange. 
    This is a general structure; specific plugins might return more detailed or different fields. 
    """
    id: str              # Exchange's order ID 
    client_order_id: Optional[str] # User-defined order ID, if supported 
    timestamp: int       # Creation timestamp in milliseconds UTC 
    datetime: str        # ISO 8601 string representation of timestamp 
    status: str          # e.g., 'open', 'closed', 'canceled', 'expired', 'rejected' 
    symbol: str          # e.g., 'BTC/USD'
    type: str            # e.g., 'limit', 'market' 
    side: str            # e.g., 'buy', 'sell' 
    price: Optional[float] # Price for limit orders 
    average: Optional[float]# Average execution price 
    amount: float        # Ordered amount 
    filled: float        # Filled amount 
    remaining: float     # Remaining amount (amount - filled)
    cost: float          # Filled amount * average price (or total cost) 
    fee: Optional[Dict[str, Any]] # Fee details (e.g., {'currency': 'USD', 'cost': 2.0, 'rate': 0.001}) 
    trades: Optional[List[Dict[str, Any]]] # List of individual trades filling this order 
    info: Dict[str, Any] # Raw response from the exchange 

class Position(TypedDict, total=False):
    """
    Represents an open trading position. Fields depend on the exchange. 
    """
    symbol: str # 
    side: str            # 'long' or 'short' 
    amount: float        # Size of the position 
    entry_price: Optional[float] # 
    mark_price: Optional[float] # 
    unrealized_pnl: Optional[float] # 
    liquidation_price: Optional[float] # 
    leverage: Optional[float] # 
    margin_type: Optional[str] # e.g., 'isolated', 'cross' 
    info: Dict[str, Any]  # Raw response from the exchange 

class Balance(TypedDict, total=False):
    """
    Represents account balance information for a single currency/asset.
    """
    free: float # 
    used: float # 
    total: float # 

class Precision(TypedDict, total=False):
    """Defines precision for amount, price, cost, base, and quote."""
    amount: Optional[int] # 
    price: Optional[int]  # 
    cost: Optional[int]   # 
    base: Optional[int]   # 
    quote: Optional[int] # 

class MarketLimits(TypedDict, total=False):
    """Defines market limits for amount, price, cost, and leverage."""
    amount: Optional[Dict[str, Optional[float]]] # e.g., {'min': 0.01, 'max': 1000} 
    price: Optional[Dict[str, Optional[float]]]  # 
    cost: Optional[Dict[str, Optional[float]]]   # 
    leverage: Optional[Dict[str, Optional[float]]] # 

class MarginTradingDetails(TypedDict, total=False):
    """Details related to margin trading capabilities for an instrument."""
    is_available: bool # 
    modes_available: Optional[List[str]] # e.g., ['isolated', 'cross'] 
    default_mode: Optional[str] # 
    max_leverage: Optional[float] # 

class InstrumentTradingDetails(TypedDict, total=False):
    """
    Comprehensive details for a specific trading instrument/symbol.
    """
    symbol: str # 
    market_type: str # e.g., 'spot', 'futures', 'options' 
    base_currency: Optional[str] # 
    quote_currency: Optional[str] # 
    is_active: Optional[bool] # Whether the instrument is currently tradable 
    precision: Optional[Precision] # 
    limits: Optional[MarketLimits] # 
    supported_order_types: Optional[List[str]] # e.g., ['market', 'limit', 'stop_loss_limit'] 
    default_order_type: Optional[str] # 
    time_in_force_options: Optional[List[str]] # e.g., ['GTC', 'IOC', 'FOK'] 
    margin_details: Optional[MarginTradingDetails] # 
    raw_exchange_info: Optional[Dict[str, Any]] # Original, unparsed info from exchange 

# --- NEW Data Structures ---
class Trade(TypedDict, total=False):
    """
    Represents a single public market trade or a user's private trade.
    """
    id: Optional[str]      # Trade ID, if available
    order_id: Optional[str]  # Order ID this trade belongs to (especially for user trades)
    timestamp: int           # Trade execution timestamp in milliseconds UTC
    datetime: str            # ISO 8601 string representation of timestamp
    symbol: str              # e.g., 'BTC/USD'
    type: Optional[str]      # e.g., 'market', 'limit' (if discernible from trade)
    side: str                # 'buy' or 'sell'
    taker_or_maker: Optional[str] # 'taker' or 'maker'
    price: float             # Execution price
    amount: float            # Amount of base currency traded
    cost: Optional[float]    # Total cost (price * amount) in quote currency
    fee: Optional[Dict[str, Any]] # Fee details (e.g., {'currency': 'USD', 'cost': 0.1, 'rate': 0.001})
    info: Dict[str, Any]     # Raw response from the exchange for this trade

class Ticker(TypedDict, total=False):
    """
    Represents ticker information for a symbol.
    """
    symbol: str              # e.g., 'BTC/USD'
    timestamp: Optional[int]   # Timestamp of the ticker data in milliseconds UTC
    datetime: Optional[str]    # ISO 8601 string representation of timestamp
    high: Optional[float]      # Highest price in the last 24h (or other period)
    low: Optional[float]       # Lowest price in the last 24h
    bid: Optional[float]       # Current best bid (buy) price
    bid_volume: Optional[float]# Volume at the current best bid
    ask: Optional[float]       # Current best ask (sell) price
    ask_volume: Optional[float]# Volume at the current best ask
    vwap: Optional[float]      # Volume Weighted Average Price
    open: Optional[float]      # Opening price of the period
    close: Optional[float]     # Last executed price (or closing price of the period)
    last: Optional[float]      # Alias for close
    previous_close: Optional[float] # Previous period's closing price
    change: Optional[float]    # Absolute change since open or previous_close
    percentage: Optional[float]# Percentage change
    average: Optional[float]   # Average price (e.g., (high + low) / 2)
    base_volume: Optional[float]# Volume traded in the base currency
    quote_volume: Optional[float]# Volume traded in the quote currency
    info: Dict[str, Any]     # Raw response from the exchange

class OrderBook(TypedDict, total=False):
    """
    Represents the order book for a symbol.
    Bids and asks are lists of [price, amount] tuples.
    """
    symbol: str
    timestamp: Optional[int]       # Timestamp of the order book snapshot in milliseconds UTC
    datetime: Optional[str]        # ISO 8601 string representation of timestamp
    bids: List[Tuple[float, float]] # List of [price, amount] tuples for bids, highest bid first
    asks: List[Tuple[float, float]] # List of [price, amount] tuples for asks, lowest ask first
    nonce: Optional[int]           # Order book sequence number, if provided
    info: Dict[str, Any]         # Raw response from the exchange

class FundingRate(TypedDict, total=False):
    """
    Represents funding rate information for a perpetual contract.
    """
    symbol: str
    mark_price: Optional[float]
    index_price: Optional[float]
    interest_rate: Optional[float]
    estimated_settle_price: Optional[float]
    timestamp: int                   # Timestamp of this funding rate data in milliseconds UTC
    datetime: str                    # ISO 8601 string
    funding_rate: Optional[float]      # The current funding rate
    funding_timestamp: Optional[int]   # Timestamp of when this funding rate applies/applied
    funding_datetime: Optional[str]    # ISO 8601 of funding_timestamp
    next_funding_rate: Optional[float] # Predicted next funding rate
    next_funding_timestamp: Optional[int] # Timestamp for the next funding event
    next_funding_datetime: Optional[str]  # ISO 8601 for next_funding_timestamp
    info: Dict[str, Any]

class Transaction(TypedDict, total=False):
    """
    Represents a deposit or withdrawal transaction.
    """
    id: str                      # Unique ID for the transaction from the exchange
    txid: Optional[str]            # Blockchain transaction ID (hash), if applicable
    currency: str                # Currency code (e.g., 'BTC', 'USD')
    amount: float                # Amount of the transaction
    address: Optional[str]         # Target address for withdrawals, source for some deposits
    address_to: Optional[str]      # Target address (alias for address)
    address_from: Optional[str]    # Source address
    tag: Optional[str]             # Destination tag, memo, or payment ID for certain currencies
    tag_to: Optional[str]          # Alias for tag
    tag_from: Optional[str]        # Source tag
    type: str                    # 'deposit' or 'withdrawal'
    status: str                  # e.g., 'pending', 'completed', 'failed', 'canceled'
    timestamp: int               # Timestamp of the transaction initiation/update in milliseconds UTC
    datetime: str                # ISO 8601 string
    network: Optional[str]         # Blockchain network used (e.g., 'ERC20', 'TRC20', 'BTC')
    fee: Optional[Dict[str, Any]]  # Fee details (e.g., {'currency': 'BTC', 'cost': 0.0001})
    info: Dict[str, Any]

class TransferEntry(TypedDict, total=False):
    """
    Represents an internal fund transfer between accounts on an exchange.
    """
    id: str                      # Unique ID for the transfer
    timestamp: int               # Timestamp of the transfer in milliseconds UTC
    datetime: str                # ISO 8601 string
    currency: str                # Currency code
    amount: float                # Amount transferred
    from_account_type: Optional[str] # e.g., 'spot', 'margin', 'futures' (exchange-specific)
    to_account_type: Optional[str]   # e.g., 'spot', 'margin', 'futures'
    status: str                  # e.g., 'completed', 'pending'
    info: Dict[str, Any]

class DepositAddress(TypedDict, total=False):
    """
    Represents a deposit address for a currency.
    """
    currency: str
    address: str
    tag: Optional[str]         # Destination tag or memo, if required
    network: Optional[str]     # Blockchain network
    info: Dict[str, Any]


# --- Type alias for the callback function used in streaming methods ---
StreamMessageCallback = Callable[[Dict[str, Any]], Awaitable[None]] # 


class MarketPlugin(abc.ABC):
    """
    Abstract base class for market data and trading plugins. 

    Each plugin class is identified by a unique `plugin_key` and declares the 
    `supported_markets` it can serve.  It must also list `provider_id`s it handles. 
    Plugin instances are configured for a specific `provider_id`, API credentials, 
    and testnet status, managed by services like `MarketService`. 
    """
    plugin_key: str = "" # 
    supported_markets: List[str] = [] # 

    def __init__(
        self,
        provider_id: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        is_testnet: bool = False,
        request_timeout: int = 30000, # milliseconds 
        verbose_logging: bool = False, # 
        **kwargs: Any # 
    ):
        """
        Initializes the MarketPlugin instance. 
        Args:
            provider_id (str): The specific provider this instance will connect to (e.g., 'binance', 'alpaca'). 
                               This ID is used to configure the underlying connection or library. 
            api_key (Optional[str]): The API key for authenticated access. 
            api_secret (Optional[str]): The API secret for authenticated access. 
            api_passphrase (Optional[str]): API passphrase, if required by the provider (e.g., Coinbase Pro). 
            is_testnet (bool): If True, the plugin should connect to the provider's sandbox/testnet environment. 
            request_timeout (int): Timeout in milliseconds for REST API requests made by the plugin. 
            verbose_logging (bool): If True, the plugin may enable more detailed internal logging. 
            **kwargs: Additional keyword arguments for plugin-specific configuration. 
        """
        if not self.__class__.plugin_key: # 
            raise ValueError(f"Plugin class '{self.__class__.__name__}' must define a non-empty 'plugin_key' attribute.") # 
        if not provider_id: # 
            raise ValueError(f"Plugin instance '{self.__class__.__name__}' must be initialized with a 'provider_id'.") # 

        self.provider_id: str = provider_id.lower() # 
        self.api_key: Optional[str] = api_key # 
        self.api_secret: Optional[str] = api_secret
        self.api_passphrase: Optional[str] = api_passphrase # 
        self.is_testnet: bool = is_testnet # 
        self.request_timeout: int = request_timeout # 
        self.verbose_logging: bool = verbose_logging # 
        self.additional_kwargs: Dict[str, Any] = kwargs # 
        logger.debug( # 
            f"Initialized {self.__class__.__name__} (PK: {self.__class__.plugin_key}) for provider '{self.provider_id}'. " # 
            f"Testnet: {self.is_testnet}, Key: {bool(self.api_key)}, Passphrase: {bool(self.api_passphrase)}"
        )

    # --- Class Methods ---
    @classmethod
    def get_plugin_key(cls) -> str:
        """Returns the unique key for this plugin type.""" # 
        if not cls.plugin_key: # 
            raise NotImplementedError(f"Plugin class {cls.__name__} must define a 'plugin_key' attribute.") # 
        return cls.plugin_key # 

    @classmethod
    def get_supported_markets(cls) -> List[str]:
        """Returns a list of market identifiers (e.g., 'crypto', 'us_equity') this plugin CLASS supports."""
        if not isinstance(cls.supported_markets, list): # 
            logger.warning(f"Plugin class {cls.__name__} 'supported_markets' is not a list. Defaulting to empty.")
            return [] # 
        return cls.supported_markets # 

    @classmethod
    @abc.abstractmethod
    def list_configurable_providers(cls) -> List[str]:
        """
        Returns a list of unique provider_ids (e.g., 'binance', 'alpaca', 'coinbasepro')
        that this plugin CLASS can be instantiated to handle. 
        """
        pass # 

    # --- Core Data Fetching (REST API based) ---
    @abc.abstractmethod
    async def get_symbols(self, market: str) -> List[str]:
        """
        Return a list of tradable symbols for this plugin's configured `provider_id`,
        optionally filtered for the specified `market` category. 
        Args:
            market (str): The market/asset class to potentially filter symbols for. 
                          Plugins should interpret this to filter results if they handle
                          multiple distinct asset classes under the same provider_id. 
        Returns:
            List[str]: A list of symbol identifiers (e.g., "BTC/USDT", "AAPL"). 
        Raises:
            PluginError, AuthenticationPluginError, NetworkPluginError. 
        """
        pass # 

    @abc.abstractmethod
    async def fetch_historical_ohlcv(
        self, 
        symbol: str, 
        timeframe: str, 
        since: Optional[int] = None, 
        limit: Optional[int] = None, 
        params: Optional[Dict[str, Any]] = None
    ) -> List[OHLCVBar]:
        """
        Fetch historical OHLCV (Open, High, Low, Close, Volume) bars for the
        given symbol and timeframe from the plugin's configured `provider_id`. 
        Args:
            symbol (str): The trading symbol (e.g., "BTC/USDT"). 
            timeframe (str): The timeframe string (e.g., "1m", "1h", "1d"). 
            since (Optional[int]): Start timestamp in milliseconds (inclusive, UTC) to fetch data from. 
            limit (Optional[int]): Maximum number of bars to return. 
            params (Optional[Dict[str, Any]]): Additional exchange-specific parameters for the API call. 
        Returns:
            List[OHLCVBar]: A list of OHLCV bars, sorted from oldest to newest. 
        Raises:
            PluginError, AuthenticationPluginError, NetworkPluginError, ValueError for bad params. 
        """
        pass # 

    @abc.abstractmethod
    async def fetch_latest_ohlcv(
        self, 
        symbol: str, 
        timeframe: str,
    ) -> Optional[OHLCVBar]:
        """
        Fetch the most recent *complete* OHLCV bar for the given symbol and timeframe. 
        This is typically used for polling updates. 

        Args:
            symbol (str): The trading symbol. 
            timeframe (str): The timeframe (e.g., "1m"). 
        Returns:
            Optional[OHLCVBar]: The latest OHLCV bar, or None if not available. 
        Raises:
            PluginError, AuthenticationPluginError, NetworkPluginError. 
        """
        pass # 

    @abc.abstractmethod
    async def fetch_historical_trades(
        self, 
        symbol: str, 
        since: Optional[int] = None, 
        limit: Optional[int] = None, 
        params: Optional[Dict[str, Any]] = None
    ) -> List[Trade]:
        """
        Fetch historical public trades for a symbol.
        Args:
            symbol (str): The trading symbol (e.g., "BTC/USDT").
            since (Optional[int]): Start timestamp in milliseconds (inclusive, UTC).
            limit (Optional[int]): Maximum number of trades to return.
            params (Optional[Dict[str, Any]]): Additional exchange-specific parameters.
        Returns:
            List[Trade]: A list of trade objects, sorted from oldest to newest.
        Raises:
            PluginError, AuthenticationPluginError (if needed), NetworkPluginError.
        """
        pass

    @abc.abstractmethod
    async def fetch_ticker(
        self, 
        symbol: str, 
        params: Optional[Dict[str, Any]] = None
    ) -> Ticker:
        """
        Fetch the latest ticker information for a single symbol.
        Args:
            symbol (str): The trading symbol.
            params (Optional[Dict[str, Any]]): Additional exchange-specific parameters.
        Returns:
            Ticker: A ticker object.
        Raises:
            PluginError, NetworkPluginError.
        """
        pass

    @abc.abstractmethod
    async def fetch_tickers(
        self, 
        symbols: Optional[List[str]] = None, 
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Ticker]:
        """
        Fetch the latest ticker information for multiple symbols or all available symbols.
        Args:
            symbols (Optional[List[str]]): A list of symbols to fetch. If None, fetch for all supported symbols.
            params (Optional[Dict[str, Any]]): Additional exchange-specific parameters.
        Returns:
            Dict[str, Ticker]: A dictionary of symbol -> ticker object.
        Raises:
            PluginError, NetworkPluginError.
        """
        pass

    @abc.abstractmethod
    async def fetch_order_book(
        self, 
        symbol: str, 
        limit: Optional[int] = None, 
        params: Optional[Dict[str, Any]] = None
    ) -> OrderBook:
        """
        Fetch the current order book for a symbol.
        Args:
            symbol (str): The trading symbol.
            limit (Optional[int]): Maximum number of bids/asks to return on each side.
            params (Optional[Dict[str, Any]]): Additional exchange-specific parameters.
        Returns:
            OrderBook: An order book object.
        Raises:
            PluginError, NetworkPluginError.
        """
        pass
        
    # --- Trading Operations (REST API based) ---
    @abc.abstractmethod
    async def place_order(self, symbol: str, order_type: str, side: str, amount: float, price: Optional[float] = None, params: Optional[Dict[str, Any]] = None) -> Order: # 
        """Places a trading order.""" # 
        pass # 

    @abc.abstractmethod
    async def cancel_order(self, order_id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: # 
        """Cancels an existing order. Returns a dictionary, structure may vary by exchange.""" # 
        pass # 

    @abc.abstractmethod
    async def get_order_status(self, order_id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Order: # 
        """Retrieves the status of a specific order.""" # 
        pass # 

    @abc.abstractmethod
    async def get_account_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Balance]: # 
        """Retrieves the account balance, mapping currency codes to Balance objects.""" # 
        pass # 

    @abc.abstractmethod
    async def get_open_positions(self, symbols: Optional[List[str]] = None, params: Optional[Dict[str, Any]] = None) -> List[Position]: # 
        """Retrieves all open trading positions, optionally filtered by symbols.""" # 
        pass # 

    @abc.abstractmethod
    async def fetch_my_trades(
        self, 
        symbol: Optional[str] = None, 
        since: Optional[int] = None, 
        limit: Optional[int] = None, 
        params: Optional[Dict[str, Any]] = None
    ) -> List[Trade]:
        """
        Fetch the history of the user's private trades.
        Args:
            symbol (Optional[str]): Filter by symbol. If None, fetch for all symbols (if supported).
            since (Optional[int]): Start timestamp in milliseconds.
            limit (Optional[int]): Maximum number of trades to return.
            params (Optional[Dict[str, Any]]): Additional parameters.
        Returns:
            List[Trade]: A list of the user's trade objects.
        Raises:
            AuthenticationPluginError, PluginError, NetworkPluginError.
        """
        pass

    @abc.abstractmethod
    async def fetch_open_orders(
        self, 
        symbol: Optional[str] = None, 
        since: Optional[int] = None, 
        limit: Optional[int] = None, 
        params: Optional[Dict[str, Any]] = None
    ) -> List[Order]:
        """
        Fetch all open orders for the user.
        Args:
            symbol (Optional[str]): Filter by symbol.
            since (Optional[int]): Filter by orders created since this timestamp.
            limit (Optional[int]): Maximum number of orders to return.
            params (Optional[Dict[str, Any]]): Additional parameters.
        Returns:
            List[Order]: A list of open order objects.
        Raises:
            AuthenticationPluginError, PluginError, NetworkPluginError.
        """
        pass
        
    @abc.abstractmethod
    async def fetch_closed_orders(
        self, 
        symbol: Optional[str] = None, 
        since: Optional[int] = None, 
        limit: Optional[int] = None, 
        params: Optional[Dict[str, Any]] = None
    ) -> List[Order]:
        """
        Fetch all closed (filled, canceled, rejected, expired) orders for the user.
        Args:
            symbol (Optional[str]): Filter by symbol.
            since (Optional[int]): Filter by orders created/closed since this timestamp.
            limit (Optional[int]): Maximum number of orders to return.
            params (Optional[Dict[str, Any]]): Additional parameters (e.g., filter by status).
        Returns:
            List[Order]: A list of closed order objects.
        Raises:
            AuthenticationPluginError, PluginError, NetworkPluginError.
        """
        pass

    async def edit_order(
        self, 
        id: str, 
        symbol: str,
        order_type: Optional[str] = None,
        side: Optional[str] = None,
        amount: Optional[float] = None, 
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Order:
        """
        (Optional) Edit/modify an existing open order. Not all exchanges support this.
        Plugins should raise PluginFeatureNotSupportedError if not implemented.
        Args:
            id (str): The ID of the order to edit.
            symbol (str): The symbol of the order (often required).
            order_type, side, amount, price: New values for the order parameters.
                                             Plugins determine which fields are editable.
            params (Optional[Dict[str, Any]]): Additional exchange-specific parameters.
        Returns:
            Order: The updated order structure.
        Raises:
            PluginFeatureNotSupportedError, AuthenticationPluginError, PluginError, NetworkPluginError.
        """
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "edit_order")


    # --- Derivative/Margin Specific (Optional methods, default to NotSupported) ---
    async def fetch_funding_rate(
        self, 
        symbol: str, 
        params: Optional[Dict[str, Any]] = None
    ) -> FundingRate:
        """(Optional) Fetch the current funding rate for a perpetual contract."""
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "fetch_funding_rate")

    async def fetch_funding_rate_history(
        self, 
        symbol: str, 
        since: Optional[int] = None, 
        limit: Optional[int] = None, 
        params: Optional[Dict[str, Any]] = None
    ) -> List[FundingRate]:
        """(Optional) Fetch historical funding rates for a perpetual contract."""
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "fetch_funding_rate_history")

    async def set_leverage(
        self, 
        symbol: str, 
        leverage: float, 
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """(Optional) Set leverage for a symbol (futures/margin). Response structure varies."""
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "set_leverage")
        
    async def fetch_leverage_tiers(
        self, 
        symbols: Optional[List[str]] = None, 
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]: # Complex structure, often dict of symbol -> tiers array
        """(Optional) Fetch leverage tiers and limits for symbols."""
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "fetch_leverage_tiers")

    async def fetch_position_risk(
        self,
        symbols: Optional[List[str]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Position]:
        """
        (Optional) Fetch risk and margin information for open positions.
        The `Position` TypedDict should be extended or used flexibly if it
        needs to include more risk-specific fields like initialMargin, maintMargin, etc.
        """
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "fetch_position_risk")


    # --- Account/Wallet Operations (Optional methods, default to NotSupported) ---
    async def fetch_deposit_address(
        self, 
        currency_code: str, 
        params: Optional[Dict[str, Any]] = None
    ) -> DepositAddress:
        """(Optional) Fetch deposit address for a currency."""
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "fetch_deposit_address")

    async def fetch_deposits(
        self, 
        currency_code: Optional[str] = None, 
        since: Optional[int] = None, 
        limit: Optional[int] = None, 
        params: Optional[Dict[str, Any]] = None
    ) -> List[Transaction]:
        """(Optional) Fetch deposit history."""
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "fetch_deposits")

    async def fetch_withdrawals(
        self, 
        currency_code: Optional[str] = None, 
        since: Optional[int] = None, 
        limit: Optional[int] = None, 
        params: Optional[Dict[str, Any]] = None
    ) -> List[Transaction]:
        """(Optional) Fetch withdrawal history."""
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "fetch_withdrawals")
        
    async def withdraw(
        self,
        currency_code: str,
        amount: float,
        address: str,
        tag: Optional[str] = None,
        network: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Transaction:
        """(Optional) Request a withdrawal. Returns a transaction object representing the withdrawal attempt."""
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "withdraw")

    async def transfer_funds(
        self,
        currency_code: str,
        amount: float,
        from_account_type: str, 
        to_account_type: str,
        params: Optional[Dict[str, Any]] = None
    ) -> TransferEntry:
        """(Optional) Transfer funds between different account types within the exchange."""
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "transfer_funds")

    # --- Metadata and Instrument Details (REST API based) ---
    @abc.abstractmethod
    async def get_instrument_trading_details(self, symbol: str, market_type: Optional[str] = 'spot') -> InstrumentTradingDetails: # 
        """Fetches detailed trading rules and parameters for a specific instrument.""" # 
        pass # 

    async def get_market_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        (Optional) Fetch detailed market information for a symbol (precision, limits, etc.).
        This method might be deprecated in favor of `get_instrument_trading_details`
        or could provide a simpler/different set of market data.
        """
        logger.debug(f"get_market_info not implemented by {self.__class__.__name__} for '{self.provider_id}'.") # 
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "get_market_info") # 

    async def validate_symbol(self, symbol: str) -> bool:
        """
        (Optional) Validate if a symbol is active and valid for the provider.
        Default implementation uses get_instrument_trading_details (preferable over get_market_info).
        Override for efficiency if a more direct validation method is available.
        """
        try:
            details = await self.get_instrument_trading_details(symbol) # Changed to use more comprehensive details
            return details is not None and details.get('is_active', True) # is_active defaults to True if not present
        except PluginFeatureNotSupportedError:
            logger.warning(f"validate_symbol uses get_instrument_trading_details, not supported by {self.get_plugin_key()} for '{self.provider_id}'. Cannot validate.") #
        except PluginError: # Catch other plugin errors during fetch
            pass # Assuming invalid if get_instrument_trading_details fails
        return False 

    async def get_supported_timeframes(self) -> Optional[List[str]]:
        """(Optional) Return a list of timeframes natively supported by the provider.""" # 
        logger.warning(f"get_supported_timeframes not explicitly implemented by {self.get_plugin_key()} for '{self.provider_id}'.") # 
        return None # 

    async def get_fetch_ohlcv_limit(self) -> int:
        """(Optional) Return max OHLCV bars per single API request for historical data.""" # 
        default_limit = 1000 # 
        logger.warning(f"get_fetch_ohlcv_limit not explicitly implemented by {self.get_plugin_key()} for '{self.provider_id}'. Defaulting to {default_limit}.")
        return default_limit # 

    async def fetch_exchange_time(self, params: Optional[Dict[str, Any]] = None) -> int:
        """(Optional) Fetch the current exchange server time in milliseconds UTC."""
        logger.warning(f"fetch_exchange_time not explicitly implemented by {self.get_plugin_key()} for '{self.provider_id}'. Falling back to local system time.")
        return int(time.time() * 1000) 

    async def fetch_exchange_status(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """(Optional) Fetch the current operational status of the exchange."""
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "fetch_exchange_status")


    # --- Real-time Data Streaming ---
    async def stream_trades(
        self, 
        symbols: List[str], 
        on_message_callback: StreamMessageCallback
    ) -> None:
        """
        Subscribe to live trade/ticker updates for the given symbols. 
        The plugin manages the WebSocket connection and invokes `on_message_callback`
        with each new message dictionary from the exchange. 
        Implementations should handle reconnections and be long-running if they manage the connection. 
        """
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "stream_trades") # 

    async def stop_trades_stream(self, symbols: List[str]) -> None:
        """Unsubscribe from live trade/ticker updates for the given symbols.""" # 
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "stop_trades_stream") # 

    async def stream_ohlcv(
        self,
        symbols: List[str],
        timeframe: str,
        on_message_callback: StreamMessageCallback
    ) -> None:
        """
        Subscribe to live OHLCV bar updates for the given symbols and timeframe. 
        Not all exchanges stream full OHLCV; this might be emulated by plugins 
        if only trade streams are available by aggregating trades into bars. 
        """
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "stream_ohlcv") # 

    async def stop_ohlcv_stream(self, symbols: List[str], timeframe: str) -> None:
        """Unsubscribe from live OHLCV updates.""" # 
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "stop_ohlcv_stream") # 
        
    async def stream_order_book(
        self, 
        symbols: List[str], 
        on_message_callback: StreamMessageCallback
    ) -> None:
        """Subscribe to live order book (Level 2) updates.""" # 
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "stream_order_book") # 

    async def stop_order_book_stream(self, symbols: List[str]) -> None:
        """Unsubscribe from live order book updates.""" # 
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "stop_order_book_stream") # 

    async def stream_user_order_updates(
        self, 
        on_message_callback: StreamMessageCallback 
    ) -> None:
        """
        Subscribe to real-time updates for the authenticated user's orders 
        (e.g., fills, status changes). 
        This is a private, authenticated stream. 
        The callback will receive `Order`-like dictionaries. 
        """
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "stream_user_order_updates") # 

    async def stop_user_order_updates_stream(self) -> None:
        """Unsubscribe from user order updates.""" # 
        raise PluginFeatureNotSupportedError(self.get_plugin_key(), self.provider_id, "stop_user_order_updates_stream") # 

    # --- Plugin Capabilities & Lifecycle ---
    async def get_supported_features(self) -> Dict[str, bool]:
        """
        Return a dictionary indicating which features are supported by this plugin instance.
        Concrete subclasses MUST override this to accurately reflect their capabilities. 
        """
        return {
            # REST API based data fetching
            "fetch_historical_ohlcv": False, # 
            "fetch_latest_ohlcv": False, # 
            "get_symbols": False, # 
            "fetch_historical_trades": False, 
            "fetch_ticker": False,            
            "fetch_tickers": False,           
            "fetch_order_book": False,        
            
            # REST API based trading
            "trading_api": False, # Covers place_order, cancel_order, get_order_status, get_account_balance, get_open_positions 
            "fetch_my_trades": False,         
            "fetch_open_orders": False,       
            "fetch_closed_orders": False,     
            "edit_order": False,              

            # REST API based derivatives/margin
            "fetch_funding_rate": False,      
            "fetch_funding_rate_history": False, 
            "set_leverage": False,            
            "fetch_leverage_tiers": False,    
            "fetch_position_risk": False,     

            # REST API based account/wallet
            "fetch_deposit_address": False,   
            "fetch_deposits": False,          
            "fetch_withdrawals": False,       
            "withdraw": False,                
            "transfer_funds": False,          

            # REST API based metadata/utils
            "get_instrument_trading_details": False, # 
            "get_market_info": False, # Default raises, so if overridden should be True
            "validate_symbol": False, # Default uses get_instrument_trading_details or get_market_info 
            "get_supported_timeframes": False, # Default returns None 
            "get_fetch_ohlcv_limit": True, # Default returns 1000 
            "fetch_exchange_time": False,     
            "fetch_exchange_status": False,   

            # Real-time Streaming via WebSockets (or emulated)
            "stream_trades": False,         # For live tickers/trades 
            "stream_ohlcv": False,          # For live OHLCV bars 
            "stream_order_book": False,     # For live L2 order book updates 
            "stream_user_order_updates": False, # For live updates on user's own orders/fills 
        }

    @abc.abstractmethod
    async def close(self) -> None:
        """
        Clean up any resources used by this plugin instance, such as closing 
        network sessions, WebSocket connections, or releasing acquired resources. 
        Called by `MarketService` when the plugin instance is no longer needed.
        Implementations should be idempotent. 
        """
        pass