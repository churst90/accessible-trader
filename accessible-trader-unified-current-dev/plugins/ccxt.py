# plugins/ccxt.py

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple, Union, Callable

import ccxt.async_support as ccxt # Import the async version of CCXT
from ccxt.base.errors import ( # Import CCXT's specific error classes
    ExchangeError,
    AuthenticationError,
    NetworkError,
    NotSupported,
    OrderNotFound,
    InvalidOrder,
    InsufficientFunds,
    RateLimitExceeded,
    ExchangeNotAvailable,
    OnMaintenance
)

from plugins.base import (MarketPlugin, OHLCVBar, Order, Trade, Ticker, OrderBook, FundingRate, Transaction, TransferEntry, DepositAddress, InstrumentTradingDetails, Precision, MarketLimits, MarginTradingDetails, Balance, Position, PluginError, AuthenticationPluginError, NetworkPluginError, PluginFeatureNotSupportedError, StreamMessageCallback)

logger = logging.getLogger(__name__) # Or "CCXTPlugin"

class CCXTPlugin(MarketPlugin):
    """
    A generic plugin that uses the CCXT library to interact with various
    cryptocurrency exchanges. It aims to implement the standard MarketPlugin
    interface by mapping its methods to the corresponding CCXT exchange methods.

    This plugin supports:
    - Fetching public market data (symbols, OHLCV, trades, tickers, order books).
    - Executing authenticated trading operations (placing/cancelling orders, fetching balances, etc.).
    - Streaming real-time data via CCXT's unified WebSocket interface (`watch_*` methods).
    """
    plugin_key: str = "ccxt_unified" # A generic key for this CCXT-based plugin
    supported_markets: List[str] = ["crypto"] # CCXT primarily focuses on crypto

    def __init__(
        self,
        provider_id: str, # This will be the CCXT exchange ID (e.g., 'binance', 'kraken')
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        is_testnet: bool = False,
        request_timeout: int = 30000,
        verbose_logging: bool = False,
        **kwargs: Any
    ):
        """
        Initializes the CCXTPlugin.

        Args:
            provider_id: The CCXT exchange ID (e.g., 'binance', 'ftx', 'kraken').
            api_key, api_secret, api_passphrase: User's API credentials.
            is_testnet: If True, attempts to use the exchange's sandbox/testnet environment.
            request_timeout: Timeout for HTTP requests in milliseconds.
            verbose_logging: If True, CCXT's internal verbose logging might be enabled (used cautiously).
            **kwargs: Additional keyword arguments for exchange-specific options.
        """
        super().__init__(
            provider_id, api_key, api_secret, api_passphrase,
            is_testnet, request_timeout, verbose_logging, **kwargs
        )

        self._streaming_tasks: Dict[Tuple[str, str], asyncio.Task] = {} # For managing watch* tasks
        self._markets_loaded = False
        self._ccxt_exchange_has_loaded = False # To track if exchange.has has been populated

        if not hasattr(ccxt, self.provider_id):
            raise PluginError(
                f"CCXT exchange ID '{self.provider_id}' is not supported by the CCXT library.",
                provider_id=self.provider_id
            )

        exchange_config = {
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'password': self.api_passphrase, # CCXT uses 'password' for passphrase
            'enableRateLimit': True,        # Recommended by CCXT
            'timeout': self.request_timeout,
            # 'verbose': self.verbose_logging, # CCXT verbose can be very noisy; manage via python logging
        }
        # Add any kwargs passed, which might be CCXT-specific options like 'uid' or 'subaccount'
        exchange_config.update(self.additional_kwargs)
        
        # Remove None values as CCXT prefers them absent
        exchange_config = {k: v for k, v in exchange_config.items() if v is not None}

        self.exchange: ccxt.Exchange = getattr(ccxt, self.provider_id)(exchange_config)

        if self.is_testnet:
            if self.exchange.has.get('test', False) or hasattr(self.exchange, 'set_sandbox_mode'):
                try:
                    self.exchange.set_sandbox_mode(True)
                    logger.info(f"CCXTPlugin ({self.provider_id}): Sandbox mode enabled.")
                except Exception as e_sandbox:
                    logger.warning(f"CCXTPlugin ({self.provider_id}): Failed to enable sandbox mode: {e_sandbox}. Testnet might not be fully functional.")
            else:
                logger.warning(f"CCXTPlugin ({self.provider_id}): Testnet mode requested, but exchange does not explicitly support sandbox mode via CCXT's set_sandbox_mode() or 'test' URL flag.")
        
        # It's good practice to load markets early, as `exchange.has` might be more accurate after.
        # However, some plugins (like this one now) call it in get_supported_features.
        # If get_supported_features is called before any other method, markets will be loaded.

    async def _ensure_markets_loaded(self):
        """Ensures that exchange markets are loaded. CCXT usually loads them on first use."""
        if not self._markets_loaded or not self.exchange.markets:
            try:
                logger.debug(f"CCXTPlugin ({self.provider_id}): Markets not loaded or empty. Attempting to load...")
                await self.exchange.load_markets()
                self._markets_loaded = True
                logger.info(f"CCXTPlugin ({self.provider_id}): Markets loaded successfully ({len(self.exchange.markets or {})} symbols).")
            except (ExchangeError, NetworkError) as e:
                raise NetworkPluginError(self.provider_id, f"Failed to load markets: {e}", original_exception=e) from e
            except Exception as e: # Catch any other unexpected error
                raise PluginError(f"Unexpected error loading markets: {e}", self.provider_id, original_exception=e) from e
        if not self.exchange.markets: # Still no markets after attempt
             raise PluginError("Markets could not be loaded.", provider_id=self.provider_id)


    # --- Helper: CCXT Error Handling ---
    def _handle_ccxt_error(self, e: Exception, context: str = "") -> PluginError:
        """Translates CCXT exceptions to PluginError hierarchy."""
        prefix = f"CCXT Error ({self.provider_id})"
        if context:
            prefix += f" during {context}"

        if isinstance(e, AuthenticationError):
            return AuthenticationPluginError(self.provider_id, f"{prefix}: {e}", original_exception=e)
        elif isinstance(e, (NetworkError, ExchangeNotAvailable, OnMaintenance)): # Includes timeouts, connection errors
            return NetworkPluginError(self.provider_id, f"{prefix}: {e}", original_exception=e)
        elif isinstance(e, NotSupported):
            return PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, f"{prefix}: Feature not supported by exchange - {e}")
        elif isinstance(e, (OrderNotFound, InvalidOrder, InsufficientFunds)): # Specific trading errors
            return PluginError(f"{prefix}: Trading error - {e}", self.provider_id, original_exception=e)
        elif isinstance(e, RateLimitExceeded):
            return NetworkPluginError(self.provider_id, f"{prefix}: API rate limit exceeded - {e}", original_exception=e) # Treat as network/transient
        elif isinstance(e, ExchangeError): # Generic CCXT exchange error
            return PluginError(f"{prefix}: {e}", self.provider_id, original_exception=e)
        else: # Other, non-CCXT errors
            return PluginError(f"Unexpected error in CCXTPlugin ({self.provider_id}) for {context}: {e}", self.provider_id, original_exception=e)

    # --- Helper: Data Transformations ---
    def _transform_ohlcv(self, ohlcv_list: list) -> OHLCVBar:
        return OHLCVBar(timestamp=int(ohlcv_list[0]), open=float(ohlcv_list[1]), high=float(ohlcv_list[2]),
                        low=float(ohlcv_list[3]), close=float(ohlcv_list[4]), volume=float(ohlcv_list[5]))

    def _transform_trade(self, ccxt_trade: dict) -> Trade:
        return Trade(
            id=ccxt_trade.get('id'),
            order_id=ccxt_trade.get('order'),
            timestamp=int(ccxt_trade['timestamp']),
            datetime=ccxt_trade['datetime'],
            symbol=ccxt_trade['symbol'],
            type=ccxt_trade.get('type'),
            side=ccxt_trade['side'],
            taker_or_maker=ccxt_trade.get('takerOrMaker'),
            price=float(ccxt_trade['price']),
            amount=float(ccxt_trade['amount']),
            cost=float(ccxt_trade['cost']) if ccxt_trade.get('cost') is not None else None,
            fee=ccxt_trade.get('fee'),
            info=ccxt_trade.get('info', {})
        )

    def _transform_order(self, ccxt_order: dict) -> Order:
        return Order(
            id=ccxt_order['id'],
            client_order_id=ccxt_order.get('clientOrderId'),
            timestamp=int(ccxt_order['timestamp']) if ccxt_order.get('timestamp') else None,
            datetime=ccxt_order.get('datetime'),
            status=ccxt_order.get('status'),
            symbol=ccxt_order['symbol'],
            type=ccxt_order['type'],
            side=ccxt_order['side'],
            price=float(ccxt_order['price']) if ccxt_order.get('price') is not None else None,
            average=float(ccxt_order.get('average')) if ccxt_order.get('average') is not None else None,
            amount=float(ccxt_order['amount']) if ccxt_order.get('amount') is not None else 0.0,
            filled=float(ccxt_order.get('filled', 0.0)),
            remaining=float(ccxt_order.get('remaining', 0.0)),
            cost=float(ccxt_order.get('cost', 0.0)),
            fee=ccxt_order.get('fee') or ccxt_order.get('fees'), # CCXT might use 'fee' or 'fees'
            trades=ccxt_order.get('trades'),
            info=ccxt_order.get('info', {})
        )
    
    def _transform_ticker(self, ccxt_ticker: dict, symbol_arg: Optional[str]=None) -> Ticker:
        # CCXT fetch_ticker often returns symbol in its payload, but fetch_tickers might not per item
        return Ticker(
            symbol=ccxt_ticker.get('symbol', symbol_arg), # Use arg if symbol not in payload
            timestamp=int(ccxt_ticker['timestamp']) if ccxt_ticker.get('timestamp') else None,
            datetime=ccxt_ticker.get('datetime'),
            high=float(ccxt_ticker['high']) if ccxt_ticker.get('high') is not None else None,
            low=float(ccxt_ticker['low']) if ccxt_ticker.get('low') is not None else None,
            bid=float(ccxt_ticker['bid']) if ccxt_ticker.get('bid') is not None else None,
            bid_volume=float(ccxt_ticker.get('bidVolume')) if ccxt_ticker.get('bidVolume') is not None else None,
            ask=float(ccxt_ticker['ask']) if ccxt_ticker.get('ask') is not None else None,
            ask_volume=float(ccxt_ticker.get('askVolume')) if ccxt_ticker.get('askVolume') is not None else None,
            vwap=float(ccxt_ticker.get('vwap')) if ccxt_ticker.get('vwap') is not None else None,
            open=float(ccxt_ticker.get('open')) if ccxt_ticker.get('open') is not None else None,
            close=float(ccxt_ticker['last']) if ccxt_ticker.get('last') is not None else (float(ccxt_ticker['close']) if ccxt_ticker.get('close') is not None else None) , # 'last' often preferred
            last=float(ccxt_ticker['last']) if ccxt_ticker.get('last') is not None else None,
            previous_close=float(ccxt_ticker.get('previousClose')) if ccxt_ticker.get('previousClose') is not None else None,
            change=float(ccxt_ticker.get('change')) if ccxt_ticker.get('change') is not None else None,
            percentage=float(ccxt_ticker.get('percentage')) if ccxt_ticker.get('percentage') is not None else None,
            average=float(ccxt_ticker.get('average')) if ccxt_ticker.get('average') is not None else None,
            base_volume=float(ccxt_ticker.get('baseVolume')) if ccxt_ticker.get('baseVolume') is not None else None,
            quote_volume=float(ccxt_ticker.get('quoteVolume')) if ccxt_ticker.get('quoteVolume') is not None else None,
            info=ccxt_ticker.get('info', {})
        )

    def _transform_order_book(self, ccxt_ob: dict, symbol_arg: Optional[str]=None) -> OrderBook:
        return OrderBook(
            symbol=ccxt_ob.get('symbol', symbol_arg),
            timestamp=int(ccxt_ob['timestamp']) if ccxt_ob.get('timestamp') else None,
            datetime=ccxt_ob.get('datetime'),
            bids=[(float(price), float(amount)) for price, amount in ccxt_ob.get('bids', [])],
            asks=[(float(price), float(amount)) for price, amount in ccxt_ob.get('asks', [])],
            nonce=ccxt_ob.get('nonce'),
            info=ccxt_ob.get('info', {})
        )
        
    def _transform_balance(self, ccxt_balance: dict) -> Dict[str, Balance]:
        balances: Dict[str, Balance] = {}
        # CCXT balance structure: {'free': {}, 'used': {}, 'total': {}, 'info': ...}
        # Or sometimes direct: {'USD': {'free': 100, 'used': 50, 'total': 150}, ...}
        
        # Handle both structures
        is_flat_structure = all(isinstance(v, dict) and 'free' in v for v in ccxt_balance.values() if k not in ['info', 'timestamp', 'datetime'])

        if is_flat_structure:
            for currency, details in ccxt_balance.items():
                if currency in ['info', 'timestamp', 'datetime']:
                    continue
                if isinstance(details, dict):
                     balances[currency] = Balance(
                        free=float(details.get('free', 0.0)),
                        used=float(details.get('used', 0.0)),
                        total=float(details.get('total', 0.0))
                    )
        else: # Standard CCXT structure with 'free', 'used', 'total' top-level keys
            all_currencies = set(ccxt_balance.get('free', {}).keys()) | \
                             set(ccxt_balance.get('used', {}).keys()) | \
                             set(ccxt_balance.get('total', {}).keys())
            for currency in all_currencies:
                balances[currency] = Balance(
                    free=float(ccxt_balance.get('free', {}).get(currency, 0.0)),
                    used=float(ccxt_balance.get('used', {}).get(currency, 0.0)),
                    total=float(ccxt_balance.get('total', {}).get(currency, 0.0))
                )
        return balances

    def _transform_position(self, ccxt_position: dict) -> Position:
         # CCXT's fetchPositions can return slightly different structures.
         # This is a general mapping attempt.
        return Position(
            symbol=ccxt_position.get('symbol'),
            side=ccxt_position.get('side'), # 'long' or 'short'
            amount=abs(float(ccxt_position.get('contracts', ccxt_position.get('contractSize', 0.0)))) if ccxt_position.get('contracts', ccxt_position.get('contractSize')) is not None else None,
            entry_price=float(ccxt_position.get('entryPrice')) if ccxt_position.get('entryPrice') is not None else None,
            mark_price=float(ccxt_position.get('markPrice')) if ccxt_position.get('markPrice') is not None else None,
            unrealized_pnl=float(ccxt_position.get('unrealizedPnl')) if ccxt_position.get('unrealizedPnl') is not None else None,
            liquidation_price=float(ccxt_position.get('liquidationPrice')) if ccxt_position.get('liquidationPrice') is not None else None,
            leverage=float(ccxt_position.get('leverage')) if ccxt_position.get('leverage') is not None else None,
            margin_type=ccxt_position.get('marginMode', ccxt_position.get('marginType')), # 'isolated' or 'cross'
            info=ccxt_position.get('info', {})
        )

    def _transform_funding_rate(self, ccxt_fr: dict) -> FundingRate:
        return FundingRate(
            symbol=ccxt_fr.get('symbol'),
            mark_price=float(ccxt_fr.get('markPrice')) if ccxt_fr.get('markPrice') is not None else None,
            index_price=float(ccxt_fr.get('indexPrice')) if ccxt_fr.get('indexPrice') is not None else None,
            interest_rate=float(ccxt_fr.get('interestRate', 0.0)), # Often 0 for perps
            funding_rate=float(ccxt_fr.get('fundingRate')) if ccxt_fr.get('fundingRate') is not None else None,
            funding_timestamp=int(ccxt_fr.get('fundingTimestamp')) if ccxt_fr.get('fundingTimestamp') is not None else None,
            funding_datetime=ccxt_fr.get('fundingDatetime'),
            timestamp=int(ccxt_fr.get('timestamp')) if ccxt_fr.get('timestamp') else None, # Timestamp of this data point
            datetime=ccxt_fr.get('datetime'),
            info=ccxt_fr.get('info', {})
        )
        
    def _transform_transaction(self, ccxt_tx: dict) -> Transaction:
        return Transaction(
            id=ccxt_tx.get('id'),
            txid=ccxt_tx.get('txid'),
            currency=ccxt_tx.get('currency'),
            amount=float(ccxt_tx.get('amount', 0.0)),
            address=ccxt_tx.get('address'),
            address_to=ccxt_tx.get('addressTo'),
            address_from=ccxt_tx.get('addressFrom'),
            tag=ccxt_tx.get('tag'),
            tag_to=ccxt_tx.get('tagTo'),
            tag_from=ccxt_tx.get('tagFrom'),
            type=ccxt_tx.get('type'), # 'deposit' or 'withdrawal'
            status=ccxt_tx.get('status'),
            timestamp=int(ccxt_tx.get('timestamp')) if ccxt_tx.get('timestamp') else None,
            datetime=ccxt_tx.get('datetime'),
            network=ccxt_tx.get('network'),
            fee=ccxt_tx.get('fee'),
            info=ccxt_tx.get('info', {})
        )

    def _transform_transfer(self, ccxt_transfer: dict) -> TransferEntry:
        return TransferEntry(
            id=ccxt_transfer.get('id'),
            timestamp=int(ccxt_transfer.get('timestamp')) if ccxt_transfer.get('timestamp') else None,
            datetime=ccxt_transfer.get('datetime'),
            currency=ccxt_transfer.get('currency'),
            amount=float(ccxt_transfer.get('amount', 0.0)),
            from_account_type=ccxt_transfer.get('fromAccount'),
            to_account_type=ccxt_transfer.get('toAccount'),
            status=ccxt_transfer.get('status'),
            info=ccxt_transfer.get('info', {})
        )

    def _transform_deposit_address(self, ccxt_addr: dict) -> DepositAddress:
        return DepositAddress(
            currency=ccxt_addr.get('currency'),
            address=ccxt_addr.get('address'),
            tag=ccxt_addr.get('tag'),
            network=ccxt_addr.get('network'),
            info=ccxt_addr.get('info', {})
        )

    def _transform_instrument_details(self, symbol: str, market_data: dict) -> InstrumentTradingDetails:
        precision = Precision(
            amount=market_data.get('precision', {}).get('amount'),
            price=market_data.get('precision', {}).get('price'),
            cost=market_data.get('precision', {}).get('cost'),
            base=market_data.get('precision', {}).get('base'),
            quote=market_data.get('precision', {}).get('quote'),
        )
        limits = MarketLimits(
            amount=market_data.get('limits', {}).get('amount'), # e.g. {'min': ..., 'max': ...}
            price=market_data.get('limits', {}).get('price'),
            cost=market_data.get('limits', {}).get('cost'),
            leverage=market_data.get('limits', {}).get('leverage'),
        )
        # CCXT `market_type` can be 'spot', 'margin', 'swap', 'future', 'option'
        # Our `InstrumentTradingDetails` expects `market_type` like 'spot', 'futures', 'options'
        # Need a mapping or direct use if compatible.
        ccxt_market_type = market_data.get('type', 'spot')
        mapped_market_type = ccxt_market_type 
        if ccxt_market_type in ['swap', 'future']:
            mapped_market_type = 'futures'
        
        # Basic margin details from CCXT flags; more advanced might need specific calls
        margin_details = None
        if market_data.get('margin', False) or ccxt_market_type == 'margin':
             margin_details = MarginTradingDetails(is_available=True) # Placeholder


        return InstrumentTradingDetails(
            symbol=market_data.get('symbol', symbol),
            market_type=mapped_market_type,
            base_currency=market_data.get('base'),
            quote_currency=market_data.get('quote'),
            is_active=market_data.get('active', True),
            precision=precision,
            limits=limits,
            supported_order_types=self.exchange.has.get('createOrderTypes', None), # CCXT may list common types
            # default_order_type: Handled by exchange or user
            # time_in_force_options: Some exchanges list this in `exchange.options['timeInForce']`
            margin_details=margin_details,
            raw_exchange_info=market_data # The full market entry from CCXT
        )

    # --- Class Methods ---
    @classmethod
    def list_configurable_providers(cls) -> List[str]:
        """Returns all exchange IDs supported by the CCXT library."""
        return ccxt.exchanges

    # --- Core Data Fetching ---
    async def get_symbols(self, market: str) -> List[str]:
        context = f"get_symbols for market '{market}'"
        try:
            await self._ensure_markets_loaded()
            symbols = []
            if self.exchange.markets:
                for sym, market_data in self.exchange.markets.items():
                    is_active = market_data.get('active', True)
                    # CCXT market types: 'spot', 'margin', 'swap', 'future', 'option'
                    # `market` arg here is our platform's market category, e.g. "crypto"
                    # We assume if a CCXT market exists, it belongs to the 'crypto' category for this plugin
                    # More sophisticated filtering by market_data['type'] could be added if `market` was e.g. 'spot_crypto', 'futures_crypto'
                    if is_active: 
                        symbols.append(sym)
            return sorted(list(set(symbols)))
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def fetch_historical_ohlcv(
        self, symbol: str, timeframe: str,
        since: Optional[int] = None, limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[OHLCVBar]:
        context = f"fetch_historical_ohlcv for {symbol}@{timeframe}"
        try:
            raw_ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, since, limit, params)
            return [self._transform_ohlcv(bar) for bar in raw_ohlcv] if raw_ohlcv else []
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def fetch_latest_ohlcv(self, symbol: str, timeframe: str) -> Optional[OHLCVBar]:
        context = f"fetch_latest_ohlcv for {symbol}@{timeframe}"
        # CCXT doesn't have a direct "latest complete bar" method.
        # Fetch 2 bars and take the second to last, assuming the last one might be incomplete.
        # Or, if exchange has 'fetchOHLCVRequiresTimestamp', calculate a recent 'since'.
        # A simpler approach for now: fetch limit=1, and assume it's the latest available.
        # For a truly "latest complete", more logic is needed based on current time vs bar timestamp.
        try:
            # Fetch a small number of recent bars to increase chance of getting a complete one
            # Some exchanges might only return current partial bar if limit=1 and no since.
            # To get the *last completed bar*, fetch 2 and pick the second to last,
            # or fetch with a since timestamp aligned to the previous bar.
            # This is a common challenge.
            # A pragmatic approach for "latest":
            raw_bars = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=2, params={'partial': False}) # if exchange supports 'partial'
            if raw_bars and len(raw_bars) > 0:
                 # If 2 bars, take the first (older one), assuming it's complete.
                 # If 1 bar, take it.
                 # This depends on exchange behavior.
                bar_to_return = raw_bars[0] if len(raw_bars) > 1 else raw_bars[-1]
                return self._transform_ohlcv(bar_to_return)
            return None
        except NotSupported: # If fetchOHLCV itself is not supported
             logger.warning(f"{context}: fetchOHLCV not supported by {self.provider_id}. Try fetch_ticker if available.")
             if self.exchange.has.get('fetchTicker'):
                 try:
                     ticker = await self.fetch_ticker(symbol)
                     if ticker and ticker.get('timestamp') and ticker.get('last') is not None: #
                         # Create a pseudo-bar if only ticker is available
                         # This is a very rough approximation
                         return OHLCVBar(timestamp=ticker['timestamp'], open=ticker['last'], high=ticker['last'], low=ticker['last'], close=ticker['last'], volume=0)
                 except Exception:
                     pass # Fall through if ticker fails
             return None #
        except Exception as e:
            logger.error(f"Error in {context} for {self.provider_id}: {e}", exc_info=True)
            # Do not re-raise as PluginError here, let it return None as per method signature
            return None


    async def fetch_historical_trades(
        self, symbol: str, since: Optional[int] = None, limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Trade]:
        context = f"fetch_historical_trades for {symbol}"
        try:
            raw_trades = await self.exchange.fetch_trades(symbol, since, limit, params)
            return [self._transform_trade(trade) for trade in raw_trades] if raw_trades else []
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def fetch_ticker(self, symbol: str, params: Optional[Dict[str, Any]] = None) -> Ticker:
        context = f"fetch_ticker for {symbol}"
        try:
            ticker_data = await self.exchange.fetch_ticker(symbol, params)
            return self._transform_ticker(ticker_data, symbol_arg=symbol)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def fetch_tickers(self, symbols: Optional[List[str]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Ticker]:
        context = "fetch_tickers"
        try:
            tickers_data = await self.exchange.fetch_tickers(symbols, params)
            return {sym: self._transform_ticker(data, symbol_arg=sym) for sym, data in tickers_data.items()}
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def fetch_order_book(self, symbol: str, limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None) -> OrderBook:
        context = f"fetch_order_book for {symbol}"
        try:
            ob_data = await self.exchange.fetch_order_book(symbol, limit, params)
            return self._transform_order_book(ob_data, symbol_arg=symbol)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    # --- Trading Operations ---
    async def place_order(self, symbol: str, order_type: str, side: str, amount: float, price: Optional[float] = None, params: Optional[Dict[str, Any]] = None) -> Order:
        context = f"place_order {side} {amount} {symbol}@{price if price else 'market'}"
        try:
            # CCXT create_order handles market type differentiation based on price being None or not
            # For specific market types (e.g. 'future', 'margin'), they are often passed in params
            # e.g. params = {'type': 'future'} or {'tradingMode': 'isolated_margin'}
            order_data = await self.exchange.create_order(symbol, order_type, side, amount, price, params)
            return self._transform_order(order_data)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        context = f"cancel_order ID:{order_id} for {symbol}"
        try:
            # CCXT cancel_order typically returns the order structure or a summary dict
            result = await self.exchange.cancel_order(order_id, symbol, params)
            if isinstance(result, dict) and 'id' in result and 'status' in result : # If it looks like an order
                return self._transform_order(result) # Return as standardized Order
            return result # Otherwise return raw CCXT response
        except OrderNotFound as e: # Specific handling for OrderNotFound
             logger.warning(f"{context}: Order not found on exchange. Error: {e}")
             raise PluginError(f"Order {order_id} not found.", self.provider_id, original_exception=e)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def get_order_status(self, order_id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Order:
        context = f"get_order_status ID:{order_id} for {symbol}"
        try:
            order_data = await self.exchange.fetch_order(order_id, symbol, params)
            return self._transform_order(order_data)
        except OrderNotFound as e:
             logger.warning(f"{context}: Order not found on exchange. Error: {e}")
             raise PluginError(f"Order {order_id} not found.", self.provider_id, original_exception=e)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def get_account_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Balance]:
        context = "get_account_balance"
        try:
            balance_data = await self.exchange.fetch_balance(params)
            return self._transform_balance(balance_data)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def get_open_positions(self, symbols: Optional[List[str]] = None, params: Optional[Dict[str, Any]] = None) -> List[Position]:
        context = "get_open_positions"
        if not self.exchange.has.get('fetchPositions'):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "get_open_positions (fetchPositions)")
        try:
            # CCXT fetch_positions takes symbols list directly
            positions_data = await self.exchange.fetch_positions(symbols, params)
            return [self._transform_position(pos) for pos in positions_data]
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def fetch_my_trades(
        self, symbol: Optional[str] = None, since: Optional[int] = None, limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Trade]:
        context = f"fetch_my_trades for {symbol or 'all'}"
        try:
            my_trades_data = await self.exchange.fetch_my_trades(symbol, since, limit, params)
            return [self._transform_trade(trade) for trade in my_trades_data] if my_trades_data else []
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def fetch_open_orders(
        self, symbol: Optional[str] = None, since: Optional[int] = None, limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Order]:
        context = f"fetch_open_orders for {symbol or 'all'}"
        try:
            orders_data = await self.exchange.fetch_open_orders(symbol, since, limit, params)
            return [self._transform_order(order) for order in orders_data] if orders_data else []
        except Exception as e:
            raise self._handle_ccxt_error(e, context)
        
    async def fetch_closed_orders(
        self, symbol: Optional[str] = None, since: Optional[int] = None, limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Order]:
        context = f"fetch_closed_orders for {symbol or 'all'}"
        try:
            orders_data = await self.exchange.fetch_closed_orders(symbol, since, limit, params)
            return [self._transform_order(order) for order in orders_data] if orders_data else []
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def edit_order(
        self, id: str, symbol: str, order_type: Optional[str] = None, side: Optional[str] = None,
        amount: Optional[float] = None, price: Optional[float] = None, params: Optional[Dict[str, Any]] = None
    ) -> Order:
        context = f"edit_order ID:{id}"
        if not self.exchange.has.get('editOrder'):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "edit_order")
        try:
            # CCXT edit_order needs specific parameters; this mapping is simplified.
            # The actual parameters required by CCXT's edit_order (type, side, amount, price)
            # need to be passed. The method signature here is a bit generic.
            # CCXT's `edit_order` often takes all original params + new ones.
            # This example assumes `params` would contain necessary overrides or existing values.
            order_data = await self.exchange.edit_order(id, symbol, order_type, side, amount, price, params)
            return self._transform_order(order_data)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    # --- Derivative/Margin Specific ---
    async def fetch_funding_rate(self, symbol: str, params: Optional[Dict[str, Any]] = None) -> FundingRate:
        context = f"fetch_funding_rate for {symbol}"
        if not self.exchange.has.get('fetchFundingRate'):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "fetch_funding_rate")
        try:
            fr_data = await self.exchange.fetch_funding_rate(symbol, params)
            return self._transform_funding_rate(fr_data)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def fetch_funding_rate_history(
        self, symbol: str, since: Optional[int] = None, limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[FundingRate]:
        context = f"fetch_funding_rate_history for {symbol}"
        if not self.exchange.has.get('fetchFundingRateHistory'):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "fetch_funding_rate_history")
        try:
            history_data = await self.exchange.fetch_funding_rate_history(symbol, since, limit, params)
            return [self._transform_funding_rate(fr) for fr in history_data] if history_data else []
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def set_leverage(self, symbol: str, leverage: float, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        context = f"set_leverage {leverage}x for {symbol}"
        if not self.exchange.has.get('setLeverage'): # CCXT uses 'setLeverage' in `has`
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "set_leverage")
        try:
            # Ensure leverage is int for some exchanges if required by CCXT for that exchange
            result = await self.exchange.set_leverage(leverage, symbol, params)
            return result # Response is exchange-specific
        except Exception as e:
            raise self._handle_ccxt_error(e, context)
        
    async def fetch_leverage_tiers(self, symbols: Optional[List[str]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        context = f"fetch_leverage_tiers for {symbols or 'all'}"
        if not self.exchange.has.get('fetchLeverageTiers'):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "fetch_leverage_tiers")
        try:
            tiers_data = await self.exchange.fetch_leverage_tiers(symbols, params)
            return tiers_data # Structure is complex and exchange-specific
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def fetch_position_risk(self, symbols: Optional[List[str]] = None, params: Optional[Dict[str, Any]] = None) -> List[Position]:
        context = f"fetch_position_risk for {symbols or 'all'}"
        # CCXT uses 'fetchPositionsRisk' for this usually, or it's part of 'fetchPositions'
        has_fetch_positions_risk = self.exchange.has.get('fetchPositionsRisk', False)
        has_fetch_positions = self.exchange.has.get('fetchPositions', False)
        
        if not (has_fetch_positions_risk or has_fetch_positions): # If neither, then not supported
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "fetch_position_risk (or fetchPositions)")
        try:
            positions_data = []
            if has_fetch_positions_risk:
                 positions_data = await self.exchange.fetch_positions_risk(symbols, params)
            elif has_fetch_positions : # Fallback to fetchPositions if specific risk endpoint is not there
                 positions_data = await self.exchange.fetch_positions(symbols, params)
            
            return [self._transform_position(pos) for pos in positions_data]
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    # --- Account/Wallet Operations ---
    async def fetch_deposit_address(self, currency_code: str, params: Optional[Dict[str, Any]] = None) -> DepositAddress:
        context = f"fetch_deposit_address for {currency_code}"
        if not self.exchange.has.get('fetchDepositAddress'):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "fetch_deposit_address")
        try:
            addr_data = await self.exchange.fetch_deposit_address(currency_code, params)
            return self._transform_deposit_address(addr_data)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def fetch_deposits(
        self, currency_code: Optional[str] = None, since: Optional[int] = None, limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Transaction]:
        context = f"fetch_deposits for {currency_code or 'all'}"
        if not self.exchange.has.get('fetchDeposits'):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "fetch_deposits")
        try:
            tx_data = await self.exchange.fetch_deposits(currency_code, since, limit, params)
            return [self._transform_transaction(tx) for tx in tx_data] if tx_data else []
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def fetch_withdrawals(
        self, currency_code: Optional[str] = None, since: Optional[int] = None, limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Transaction]:
        context = f"fetch_withdrawals for {currency_code or 'all'}"
        if not self.exchange.has.get('fetchWithdrawals'):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "fetch_withdrawals")
        try:
            tx_data = await self.exchange.fetch_withdrawals(currency_code, since, limit, params)
            return [self._transform_transaction(tx) for tx in tx_data] if tx_data else []
        except Exception as e:
            raise self._handle_ccxt_error(e, context)
        
    async def withdraw(
        self, currency_code: str, amount: float, address: str,
        tag: Optional[str] = None, network: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> Transaction:
        context = f"withdraw {amount} {currency_code} to {address}"
        if not self.exchange.has.get('withdraw'):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "withdraw")
        
        # CCXT withdraw params can be tricky. `params` often includes network.
        ccxt_params = params.copy() if params else {}
        if network and 'network' not in ccxt_params: # Some exchanges put network in params
            ccxt_params['network'] = network
            
        try:
            tx_data = await self.exchange.withdraw(currency_code, amount, address, tag, ccxt_params)
            return self._transform_transaction(tx_data)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def transfer_funds(
        self, currency_code: str, amount: float, from_account_type: str, to_account_type: str, params: Optional[Dict[str, Any]] = None
    ) -> TransferEntry:
        context = f"transfer_funds {amount} {currency_code} from {from_account_type} to {to_account_type}"
        if not self.exchange.has.get('transfer'):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "transfer_funds")
        try:
            # CCXT account types for transfer: 'spot', 'margin', 'funding', 'future', 'swap', etc.
            # These need to map to your platform's understanding or be passed directly.
            transfer_data = await self.exchange.transfer(currency_code, amount, from_account_type, to_account_type, params)
            return self._transform_transfer(transfer_data)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    # --- Metadata and Instrument Details ---
    async def get_instrument_trading_details(self, symbol: str, market_type: Optional[str] = 'spot') -> InstrumentTradingDetails:
        context = f"get_instrument_trading_details for {symbol} (type: {market_type})"
        try:
            await self._ensure_markets_loaded()
            market_data = self.exchange.market(symbol) # CCXT's helper to get a specific market
            if not market_data:
                raise PluginError(f"Symbol {symbol} not found in loaded markets for {self.provider_id}.", self.provider_id)
            
            # If market_type is provided, we might want to ensure the fetched market_data matches.
            # CCXT's market_data already contains 'type' (spot, future, swap, option, margin)
            ccxt_type = market_data.get('type', 'spot')
            if market_type: # User specified a market_type
                # Basic mapping from our terms to CCXT terms if needed
                expected_ccxt_type = market_type
                if market_type == 'futures': expected_ccxt_type = ['future', 'swap'] # Accept either
                elif market_type == 'spot': expected_ccxt_type = ['spot', 'margin'] # Margin often uses spot market data

                if isinstance(expected_ccxt_type, list) and ccxt_type not in expected_ccxt_type:
                     raise PluginError(f"Market data for {symbol} is of type '{ccxt_type}', not matching requested type(s) '{expected_ccxt_type}'.", self.provider_id)
                elif isinstance(expected_ccxt_type, str) and ccxt_type != expected_ccxt_type:
                     raise PluginError(f"Market data for {symbol} is of type '{ccxt_type}', not '{expected_ccxt_type}'.", self.provider_id)
            
            return self._transform_instrument_details(symbol, market_data)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def get_supported_timeframes(self) -> Optional[List[str]]:
        # CCXT stores available timeframes in `exchange.timeframes`
        if hasattr(self.exchange, 'timeframes') and self.exchange.timeframes:
            return list(self.exchange.timeframes.keys())
        logger.warning(f"get_supported_timeframes: No timeframes listed by CCXT for {self.provider_id}.")
        return None # Default from base

    async def get_fetch_ohlcv_limit(self) -> int:
        # This is not a standard property in CCXT exchanges.
        # Common limits are 500, 1000, 1500. Defaulting to base's 1000 is reasonable.
        # Some exchanges might expose this, or it can be hardcoded per provider if known.
        return await super().get_fetch_ohlcv_limit() 

    async def fetch_exchange_time(self, params: Optional[Dict[str, Any]] = None) -> int:
        context = "fetch_exchange_time"
        if not self.exchange.has.get('fetchTime'):
            return await super().fetch_exchange_time(params) # Use base's fallback
        try:
            return await self.exchange.fetch_time(params)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)

    async def fetch_exchange_status(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        context = "fetch_exchange_status"
        if not self.exchange.has.get('fetchStatus'):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "fetch_exchange_status")
        try:
            return await self.exchange.fetch_status(params)
        except Exception as e:
            raise self._handle_ccxt_error(e, context)


    # --- Real-time Data Streaming ---
    async def _run_watch_loop(self, ccxt_watch_method_name: str, symbols_or_symbol: Union[str, List[str]], 
                              stream_identifier_tuple: tuple, on_message_callback: StreamMessageCallback, 
                              transform_method: Callable, **kwargs):
        """
        Generic loop to run a CCXT watch_* method and call the callback.
        `kwargs` are additional parameters for the CCXT watch method (e.g., timeframe).
        """
        method_to_call = getattr(self.exchange, ccxt_watch_method_name)
        log_prefix = f"CCXTWatchLoop ({self.provider_id}, {stream_identifier_tuple})"
        logger.info(f"{log_prefix}: Starting for {symbols_or_symbol} with method {ccxt_watch_method_name}.")

        while stream_identifier_tuple in self._streaming_tasks: # Check if still active
            try:
                # CCXT watch methods typically take a single symbol or a list of symbols
                # and additional params like timeframe.
                if ccxt_watch_method_name in ['watchOHLCV', 'watchOrderBook', 'watchTrades']: # Methods taking one symbol at a time for watch
                    if not isinstance(symbols_or_symbol, str): # Should be single symbol for these
                        logger.error(f"{log_prefix}: {ccxt_watch_method_name} expects a single symbol string, got {type(symbols_or_symbol)}. Stopping task.")
                        break
                    data_list = await method_to_call(symbols_or_symbol, **kwargs) # e.g. await exchange.watch_ohlcv(symbol, timeframe)
                elif ccxt_watch_method_name in ['watchTickers']: # Methods that can take multiple symbols
                     data_list = await method_to_call(symbols_or_symbol if symbols_or_symbol else None, **kwargs) # Pass None for all if symbols_or_symbol is empty/None
                else: # watchOrders, watchMyTrades, watchBalance usually don't take symbol list, or symbol is optional
                    # For watchOrders, symbol might be an arg in kwargs
                    # For watchMyTrades, symbol might be an arg in kwargs
                    # For watchBalance, no symbol needed
                    data_list = await method_to_call(**kwargs) # Pass kwargs like symbol if needed by specific watch_ method

                # CCXT watch methods usually return a list, even if it's a list of one item (e.g. watchTicker)
                # or a list of updates since last call (e.g. watchTrades)
                if not isinstance(data_list, list): # Ensure it's a list for consistent processing
                    if data_list is not None: # If it's a single dict (like watchTicker sometimes)
                        data_list = [data_list]
                    else: # If None, skip
                        continue
                
                for item_data in data_list:
                    try:
                        # Transform data (item_data is raw from CCXT)
                        # The transform_method should handle if item_data is not what's expected
                        transformed_payload = transform_method(item_data)
                        
                        # Add context for the _handle_plugin_message in StreamingManager
                        # _handle_plugin_message will use stream_key_for_context if these are missing.
                        # It's good practice for plugin to add them if readily available.
                        if isinstance(transformed_payload, dict):
                            transformed_payload.setdefault('provider', self.provider_id)
                            # Symbol might be in item_data already from CCXT, or use context
                            if 'symbol' not in transformed_payload:
                                if isinstance(symbols_or_symbol, str): # If single symbol stream
                                    transformed_payload['symbol'] = symbols_or_symbol
                                elif item_data.get('symbol'): # If item itself has symbol (e.g. from watchTickers)
                                     transformed_payload['symbol'] = item_data.get('symbol')
                            
                            transformed_payload.setdefault('stream_type', stream_identifier_tuple[0].replace('watch','').lower()) # e.g. 'trades' from 'watchTrades'
                            if 'timeframe' in kwargs and 'timeframe' not in transformed_payload:
                                transformed_payload['timeframe'] = kwargs['timeframe']

                            await on_message_callback(transformed_payload)
                        else:
                            logger.warning(f"{log_prefix}: Transformed payload is not a dict, cannot send: {type(transformed_payload)}")

                    except Exception as e_item_proc:
                        logger.error(f"{log_prefix}: Error processing/transforming item from {ccxt_watch_method_name}: {item_data}. Error: {e_item_proc}", exc_info=True)

            except asyncio.CancelledError:
                logger.info(f"{log_prefix}: Task cancelled for {symbols_or_symbol}.")
                break
            except NotSupported as e_ns:
                logger.error(f"{log_prefix}: {ccxt_watch_method_name} not supported by {self.provider_id} for {symbols_or_symbol} or params. Stopping task. Error: {e_ns}")
                self._handle_stream_task_exception(stream_identifier_tuple)
                break
            except Exception as e_watch:
                logger.error(f"{log_prefix}: Error in watch loop for {symbols_or_symbol} ({ccxt_watch_method_name}): {e_watch}", exc_info=True)
                # Decide on retry/backoff strategy or break
                await asyncio.sleep(self.exchange.rateLimit / 1000 if self.exchange.rateLimit else 5) # Use exchange's rateLimit or default
        
        logger.info(f"{log_prefix}: Exited watch loop for {symbols_or_symbol} ({ccxt_watch_method_name}).")
        # Ensure task is removed from tracking if loop exits normally (e.g. due to NotSupported)
        async with self._management_lock: # Assuming a lock for _streaming_tasks exists in StreamingManager
            self._streaming_tasks.pop(stream_identifier_tuple, None)


    def _handle_stream_task_exception(self, stream_id: tuple):
        """Helper to clean up a task from _streaming_tasks upon unrecoverable error."""
        # This should ideally be called from within the _run_watch_loop on errors like NotSupported
        # to ensure the task is removed from tracking if it stops itself.
        # It requires _streaming_tasks to be accessible or a lock if modified here.
        # For now, rely on the outer management (StreamingManager) to also track.
        logger.debug(f"CCXTPlugin ({self.provider_id}): Cleaning up stream task {stream_id} due to exception.")
        self._streaming_tasks.pop(stream_id, None)


    async def _start_generic_stream(self, watch_method_name: str, transform_method: Callable,
                                    symbols: List[str], on_message_callback: StreamMessageCallback,
                                    stream_type_id_prefix: str, **kwargs):
        """
        Generic helper to start streaming for methods that watch one symbol at a time.
        `kwargs` are passed to `_run_watch_loop` and then to the CCXT `watch_` method.
        """
        if not getattr(self.exchange.has, watch_method_name.replace("watch","").lower(), self.exchange.has.get(watch_method_name, False)): # Check general support
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, f"{watch_method_name}")

        for symbol in symbols:
            # Create a unique identifier for this specific stream task
            # For OHLCV, kwargs will include timeframe.
            timeframe_suffix = f"_{kwargs['timeframe']}" if 'timeframe' in kwargs else ""
            stream_id_tuple = (f"{stream_type_id_prefix}{timeframe_suffix}", symbol) 

            if stream_id_tuple in self._streaming_tasks and not self._streaming_tasks[stream_id_tuple].done():
                logger.warning(f"CCXTPlugin ({self.provider_id}): Already streaming {stream_id_tuple}. Ignoring duplicate request.")
                continue
            
            # Add symbol to kwargs if not already there and needed by watch method signature
            # (Most watch methods take symbol as first arg, handled by _run_watch_loop)
            
            task = asyncio.create_task(
                self._run_watch_loop(watch_method_name, symbol, stream_id_tuple, on_message_callback, transform_method, **kwargs)
            )
            self._streaming_tasks[stream_id_tuple] = task

    async def _stop_generic_stream(self, symbols: List[str], stream_type_id_prefix: str, timeframe: Optional[str]=None):
        """Generic helper to stop streaming tasks for methods watching one symbol at a time."""
        for symbol in symbols:
            timeframe_suffix = f"_{timeframe}" if timeframe else ""
            stream_id_tuple = (f"{stream_type_id_prefix}{timeframe_suffix}", symbol)
            
            task = self._streaming_tasks.pop(stream_id_tuple, None)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(f"CCXTPlugin ({self.provider_id}): Stream {stream_id_tuple} cancelled successfully.")
                except Exception as e:
                    logger.error(f"CCXTPlugin ({self.provider_id}): Error awaiting cancelled stream {stream_id_tuple}: {e}")
            else:
                logger.info(f"CCXTPlugin ({self.provider_id}): No active stream {stream_id_tuple} found to stop.")


    async def stream_trades(self, symbols: List[str], on_message_callback: StreamMessageCallback) -> None:
        await self._start_generic_stream('watchTrades', self._transform_trade, symbols, on_message_callback, 'trades')

    async def stop_trades_stream(self, symbols: List[str]) -> None:
        await self._stop_generic_stream(symbols, 'trades')

    async def stream_ohlcv(self, symbols: List[str], timeframe: str, on_message_callback: StreamMessageCallback) -> None:
        await self._ensure_markets_loaded() # Timeframes depend on loaded markets for some exchanges
        if not self.exchange.timeframes or timeframe not in self.exchange.timeframes:
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, f"stream_ohlcv (timeframe {timeframe} not supported by exchange)")
        await self._start_generic_stream('watchOHLCV', self._transform_ohlcv, symbols, on_message_callback, 'ohlcv', timeframe=timeframe)

    async def stop_ohlcv_stream(self, symbols: List[str], timeframe: str) -> None:
        await self._stop_generic_stream(symbols, 'ohlcv', timeframe=timeframe)

    async def stream_order_book(self, symbols: List[str], on_message_callback: StreamMessageCallback) -> None:
        # CCXT's watchOrderBook takes additional params like limit. For now, using defaults.
        await self._start_generic_stream('watchOrderBook', self._transform_order_book, symbols, on_message_callback, 'order_book')

    async def stop_order_book_stream(self, symbols: List[str]) -> None:
        await self._stop_generic_stream(symbols, 'order_book')

    async def stream_user_order_updates(self, on_message_callback: StreamMessageCallback) -> None:
        # watchOrders usually takes an optional symbol argument. If None, streams all order updates.
        # We need a way to identify this stream without a symbol for _streaming_tasks key.
        if not self.exchange.has.get('watchOrders'):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "stream_user_order_updates (watchOrders)")

        stream_id_tuple = ('user_orders', self.provider_id) # Unique key for this user-wide stream
        if stream_id_tuple in self._streaming_tasks and not self._streaming_tasks[stream_id_tuple].done():
            logger.warning(f"CCXTPlugin ({self.provider_id}): Already streaming user orders. Ignoring.")
            return
        task = asyncio.create_task(
            self._run_watch_loop('watchOrders', '', stream_id_tuple, on_message_callback, self._transform_order) # Empty symbol for all
        )
        self._streaming_tasks[stream_id_tuple] = task
        
    async def stop_user_order_updates_stream(self) -> None:
        stream_id_tuple = ('user_orders', self.provider_id)
        task = self._streaming_tasks.pop(stream_id_tuple, None)
        if task and not task.done():
            task.cancel()
            try: await task
            except asyncio.CancelledError: logger.info(f"CCXTPlugin ({self.provider_id}): User order stream cancelled.")
            except Exception as e: logger.error(f"CCXTPlugin ({self.provider_id}): Error awaiting user order stream cancel: {e}")
        else: logger.info(f"CCXTPlugin ({self.provider_id}): No active user order stream found to stop.")

    # --- Plugin Capabilities & Lifecycle ---
    async def get_supported_features(self) -> Dict[str, bool]:
        if not self._ccxt_exchange_has_loaded: # Ensure `exchange.has` is populated
            try:
                # Some `exchange.has` flags are only accurate after markets are loaded or first API call.
                # Loading markets is a good general pre-check.
                await self._ensure_markets_loaded() 
                # A light, inexpensive call like fetch_time can also help populate `has`
                if self.exchange.has.get('fetchTime'):
                    await self.exchange.fetch_time()
                self._ccxt_exchange_has_loaded = True
            except Exception as e:
                logger.warning(f"CCXTPlugin ({self.provider_id}): Could not fully populate 'exchange.has' due to error: {e}. Feature flags may be incomplete.")
        
        # Map CCXT 'has' capabilities to our feature flags
        has = self.exchange.has
        features = {
            # REST Data
            "get_symbols": True, # Always true, relies on load_markets
            "fetch_historical_ohlcv": has.get('fetchOHLCV', False),
            "fetch_latest_ohlcv": has.get('fetchOHLCV', False) or has.get('fetchTicker', False), # Can emulate with ticker
            "fetch_historical_trades": has.get('fetchTrades', False),
            "fetch_ticker": has.get('fetchTicker', False),
            "fetch_tickers": has.get('fetchTickers', False),
            "fetch_order_book": has.get('fetchOrderBook', False),
            
            # REST Trading
            "place_order": has.get('createOrder', False),
            "cancel_order": has.get('cancelOrder', False),
            "get_order_status": has.get('fetchOrder', False),
            "get_account_balance": has.get('fetchBalance', False),
            "get_open_positions": has.get('fetchPositions', False) or has.get('fetchOpenPositions', False), # CCXT has variations
            "fetch_my_trades": has.get('fetchMyTrades', False),
            "fetch_open_orders": has.get('fetchOpenOrders', False),
            "fetch_closed_orders": has.get('fetchClosedOrders', False),
            "edit_order": has.get('editOrder', False),

            # REST Derivatives/Margin
            "fetch_funding_rate": has.get('fetchFundingRate', False),
            "fetch_funding_rate_history": has.get('fetchFundingRateHistory', False),
            "set_leverage": has.get('setLeverage', False), # Note: CCXT uses setLeverage(leverage, symbol, params)
            "fetch_leverage_tiers": has.get('fetchLeverageTiers', False),
            "fetch_position_risk": has.get('fetchPositionsRisk', False) or has.get('fetchPositions', False), # If positions include risk

            # REST Account/Wallet
            "fetch_deposit_address": has.get('fetchDepositAddress', False),
            "fetch_deposits": has.get('fetchDeposits', False),
            "fetch_withdrawals": has.get('fetchWithdrawals', False),
            "withdraw": has.get('withdraw', False),
            "transfer_funds": has.get('transfer', False),

            # REST Metadata/Utils
            "get_instrument_trading_details": True, # Relies on loaded markets
            "get_market_info": False, # We are prioritizing get_instrument_trading_details
            "validate_symbol": True, # Relies on loaded markets
            "get_supported_timeframes": True, # Relies on exchange.timeframes
            "get_fetch_ohlcv_limit": True, # Using base's default, can be overridden if CCXT provides
            "fetch_exchange_time": has.get('fetchTime', False),
            "fetch_exchange_status": has.get('fetchStatus', False),

            # Streaming (Unified WebSocket Interface)
            "stream_trades": has.get('watchTrades', False),
            "stream_ohlcv": has.get('watchOHLCV', False),
            "stream_order_book": has.get('watchOrderBook', False),
            "stream_user_order_updates": has.get('watchOrders', False), # CCXT's watchOrders for user's orders
            # Consider adding:
            # "stream_my_trades": has.get('watchMyTrades', False),
            # "stream_balance": has.get('watchBalance', False),
            # "stream_positions": has.get('watchPositions', False), # For futures
        }
        # Ensure the combined "trading_api" flag is set if any core trading methods are true
        features["trading_api"] = any([
            features["place_order"], features["cancel_order"], features["get_order_status"],
            features["get_account_balance"], features["get_open_positions"]
        ])
        return features

    async def close(self) -> None:
        """Gracefully close all connections and clean up resources."""
        logger.info(f"CCXTPlugin ({self.provider_id}): Initiating close sequence.")
        
        # Cancel all active streaming tasks
        active_tasks_to_await = []
        for stream_id, task in list(self._streaming_tasks.items()): # Iterate over a copy
            if task and not task.done():
                logger.debug(f"CCXTPlugin ({self.provider_id}): Cancelling task for stream {stream_id}.")
                task.cancel()
                active_tasks_to_await.append(task)
        
        if active_tasks_to_await:
            results = await asyncio.gather(*active_tasks_to_await, return_exceptions=True)
            for i, result in enumerate(results):
                stream_id_for_log = active_tasks_to_await[i].get_name() if hasattr(active_tasks_to_await[i], 'get_name') else "N/A"
                if isinstance(result, asyncio.CancelledError):
                    logger.debug(f"CCXTPlugin ({self.provider_id}): Streaming task {stream_id_for_log} successfully cancelled during close.")
                elif isinstance(result, Exception):
                    logger.error(f"CCXTPlugin ({self.provider_id}): Error encountered while awaiting cancelled task {stream_id_for_log}: {result}", exc_info=True)
        self._streaming_tasks.clear()
        
        # Close the CCXT exchange connection
        if hasattr(self.exchange, 'close') and callable(self.exchange.close):
            try:
                await self.exchange.close()
                logger.info(f"CCXTPlugin ({self.provider_id}): CCXT exchange connection closed successfully.")
            except Exception as e:
                logger.error(f"CCXTPlugin ({self.provider_id}): Error closing CCXT exchange connection: {e}", exc_info=True)
        logger.info(f"CCXTPlugin ({self.provider_id}): Close sequence completed.")