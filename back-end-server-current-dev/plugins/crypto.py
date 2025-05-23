# plugins/crypto.py

import asyncio
import logging
import time # For instance-cache timestamps
import random # For retry jitter
from typing import Any, Dict, List, Optional, Type

import ccxt.async_support as ccxt
from ccxt.base.errors import (
    AuthenticationError as CCXTAuthenticationError,
    ExchangeError as CCXTExchangeError,
    ExchangeNotAvailable as CCXTExchangeNotAvailable,
    NetworkError as CCXTNetworkError,
    RateLimitExceeded as CCXTRateLimitExceeded,
    RequestTimeout as CCXTRequestTimeout,
    BadSymbol as CCXTBadSymbol,
    NotSupported as CCXTNotSupported
)
# Assuming current_app is available for config access if needed for cache TTLs from a central place
# from quart import current_app

from plugins.base import (
    MarketPlugin,
    PluginError,
    AuthenticationPluginError,
    NetworkPluginError,
    PluginFeatureNotSupportedError,
    OHLCVBar
)
from utils.timeframes import (
    format_timestamp_to_iso, # For logging
    # We'll use a CCXT-specific normalizer or ensure input is already CCXT-like
)

logger = logging.getLogger(__name__)

# Default retry configuration for CCXT calls
DEFAULT_CCXT_RETRY_COUNT = 3
DEFAULT_CCXT_RETRY_DELAY_BASE_S = 0.75
MARKET_CACHE_TTL_SECONDS = 3600 # Cache market data (symbols, etc.) for 1 hour

class CryptoPlugin(MarketPlugin):
    """
    CryptoPlugin interfaces with various cryptocurrency exchanges using the CCXT library.

    This plugin class is identified by `plugin_key = "crypto"` and primarily serves
    the "crypto" market. An instance of this plugin is configured for a specific
    CCXT exchange ID (provider_id, e.g., 'binance', 'coinbasepro').
    It manages its own CCXT exchange object, handles API credentials, testnet modes,
    and provides methods for fetching symbols, OHLCV data, and other metadata.
    Instance-level caches are used for metadata to improve performance.
    """
    plugin_key: str = "crypto"
    supported_markets: List[str] = ["crypto"]

    def __init__(
        self,
        provider_id: str, # e.g., 'binance', 'coinbasepro' - the specific CCXT exchange ID
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        is_testnet: bool = False,
        request_timeout: int = 30000, # Milliseconds
        verbose_logging: bool = False,
        retry_count: int = DEFAULT_CCXT_RETRY_COUNT,
        retry_delay_base: float = DEFAULT_CCXT_RETRY_DELAY_BASE_S,
        **kwargs: Any
    ):
        """
        Initializes a CryptoPlugin instance for a specific CCXT exchange provider.

        Args:
            provider_id (str): CCXT exchange ID (e.g., 'binance', 'coinbasepro').
            api_key (Optional[str]): API key for authenticated requests.
            api_secret (Optional[str]): API secret for authenticated requests.
            api_passphrase (Optional[str]): API passphrase, if required by the exchange.
            is_testnet (bool): Use testnet/sandbox mode if True.
            request_timeout (int): CCXT request timeout in milliseconds.
            verbose_logging (bool): Enable verbose CCXT logging if True.
            retry_count (int): Number of retries for transient CCXT API errors.
            retry_delay_base (float): Base delay in seconds for exponential backoff retries.
            **kwargs: Catches any other arguments passed from MarketService.
        """
        super().__init__(
            provider_id=provider_id,
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=api_passphrase,
            is_testnet=is_testnet,
            request_timeout=request_timeout,
            verbose_logging=verbose_logging,
            **kwargs
        )

        self._exchange: Optional[ccxt.Exchange] = None
        self._exchange_lock = asyncio.Lock() # Lock for initializing self._exchange

        self.retry_count = retry_count
        self.retry_delay_base = retry_delay_base

        # Instance-specific caches with timestamps for expiry
        self._all_markets_data: Optional[Dict[str, Any]] = None
        self._all_markets_timestamp: float = 0.0
        self._supported_timeframes: Optional[List[str]] = None
        self._fetch_limit: Optional[int] = None
        # No separate _validate_symbol_cache or _market_info_cache;
        # these will rely on _all_markets_data.

        logger.info(
            f"CryptoPlugin instance (class_key: '{self.plugin_key}') initialized for Provider ID: '{self.provider_id}'. "
            f"Testnet: {self.is_testnet}, API Key Provided: {bool(self.api_key)}. "
            f"CCXT Version: {getattr(ccxt, '__version__', 'unknown')}"
        )

    @classmethod
    def get_plugin_key(cls) -> str:
        return cls.plugin_key

    @classmethod
    def get_supported_markets(cls) -> List[str]:
        return cls.supported_markets

    @classmethod
    def list_configurable_providers(cls) -> List[str]:
        """Returns a list of all CCXT exchange provider IDs this CryptoPlugin class can handle."""
        try:
            return sorted(list(ccxt.exchanges))
        except Exception as e:
            logger.error(f"Failed to retrieve list of CCXT exchanges: {e}")
            return []

    async def _get_exchange(self) -> ccxt.Exchange:
        """
        Retrieves or initializes the CCXT exchange object for this plugin instance,
        configured for `self.provider_id`. Handles testnet mode and API credentials.
        This method is idempotent for the lifetime of the plugin instance.
        """
        if self._exchange is not None:
            return self._exchange

        async with self._exchange_lock:
            if self._exchange is not None: # Double-check after acquiring lock
                return self._exchange

            exchange_id_to_load = self.provider_id
            logger.debug(f"CryptoPlugin (Instance for '{self.provider_id}'): Initializing CCXT exchange object.")

            if not hasattr(ccxt, exchange_id_to_load):
                available_exchanges = ", ".join(ccxt.exchanges)
                error_msg = f"Exchange ID '{exchange_id_to_load}' not found in CCXT library. Available: {available_exchanges}"
                logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): {error_msg}")
                raise PluginError(message=error_msg, provider_id=self.provider_id)

            try:
                exchange_class: Type[ccxt.Exchange] = getattr(ccxt, exchange_id_to_load)
                
                exchange_config: Dict[str, Any] = {
                    'timeout': self.request_timeout,
                    'enableRateLimit': True, # Use CCXT's built-in rate limiter
                    'verbose': self.verbose_logging,
                    'options': {'defaultType': 'spot'} # Default to spot markets
                }

                if self.api_key: exchange_config['apiKey'] = self.api_key
                if self.api_secret: exchange_config['secret'] = self.api_secret
                if self.api_passphrase: exchange_config['password'] = self.api_passphrase # CCXT uses 'password'

                instance = exchange_class(exchange_config)

                if self.is_testnet:
                    logger.debug(f"CryptoPlugin (Instance for '{self.provider_id}'): Configuring for testnet mode.")
                    if hasattr(instance, 'set_sandbox_mode') and callable(instance.set_sandbox_mode):
                        try:
                            if asyncio.iscoroutinefunction(instance.set_sandbox_mode):
                                await instance.set_sandbox_mode(True)
                            else:
                                instance.set_sandbox_mode(True) # type: ignore
                            logger.info(f"CryptoPlugin (Instance for '{self.provider_id}'): Sandbox mode explicitly set via set_sandbox_mode(True).")
                        except Exception as e_sandbox:
                            logger.warning(f"CryptoPlugin (Instance for '{self.provider_id}'): Could not call set_sandbox_mode: {e_sandbox}. Testnet functionality might rely on URL or options.", exc_info=True)
                    elif 'test' in getattr(instance, 'urls', {}):
                        instance.urls['api'] = instance.urls['test'] # Switch to testnet URL if available
                        logger.info(f"CryptoPlugin (Instance for '{self.provider_id}'): Switched to testnet URLs. Current API URL: {instance.urls.get('api')}")
                    else:
                        logger.warning(f"CryptoPlugin (Instance for '{self.provider_id}'): Testnet mode requested, but no standard 'set_sandbox_mode' method or 'test' URL found. Testnet functionality depends on exchange-specific CCXT implementation.")
                
                self._exchange = instance
                logger.info(
                    f"CryptoPlugin (Instance for '{self.provider_id}'): CCXT exchange object initialized. "
                    f"Testnet: {self.is_testnet}, API Key Used: {bool(self.api_key)}."
                )
                return self._exchange

            except CCXTAuthenticationError as e:
                logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): CCXT AuthenticationError during exchange init: {e}.", exc_info=True)
                raise AuthenticationPluginError(provider_id=self.provider_id, original_exception=e) from e
            except (CCXTRequestTimeout, CCXTNetworkError, CCXTExchangeNotAvailable) as e:
                logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): CCXT Network/Timeout/Availability error during exchange init: {e}", exc_info=True)
                raise NetworkPluginError(provider_id=self.provider_id, original_exception=e) from e
            except CCXTExchangeError as e: # Broader CCXT exchange error
                logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): CCXT ExchangeError during exchange init: {e}", exc_info=True)
                raise PluginError(message=f"Exchange setup error with '{self.provider_id}': {e}", provider_id=self.provider_id, original_exception=e) from e
            except Exception as e: # Catch-all for other unexpected errors
                logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): Unexpected error initializing CCXT exchange: {e}", exc_info=True)
                raise PluginError(message=f"Unexpected initialization failure for '{self.provider_id}': {e}", provider_id=self.provider_id, original_exception=e) from e

    async def _call_ccxt_method(self, method_name: str, *args, params: Optional[Dict[str, Any]] = None, **kwargs) -> Any:
        """
        Helper to call a CCXT exchange method with retries and error wrapping.
        Now accepts **kwargs to pass through additional keyword arguments like 'reload'.
        """
        exchange = await self._get_exchange()
        if not hasattr(exchange, method_name):
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, method_name)

        ccxt_method_to_call = getattr(exchange, method_name)
        last_exception: Optional[Exception] = None

        for attempt in range(self.retry_count + 1):
            try:
                if self.verbose_logging:
                    logger.debug(f"CryptoPlugin ('{self.provider_id}'): Calling {method_name} with args: {args}, params: {params}, kwargs: {kwargs} (Attempt: {attempt + 1})")
                
                # Construct arguments for the CCXT method call
                call_kwargs = {}
                if params:
                    call_kwargs['params'] = params
                call_kwargs.update(kwargs) # Add any other direct keyword arguments

                return await ccxt_method_to_call(*args, **call_kwargs)

            except (CCXTRateLimitExceeded, CCXTRequestTimeout, CCXTNetworkError, CCXTExchangeNotAvailable) as e:
                last_exception = e
                if attempt == self.retry_count:
                    logger.error(f"CryptoPlugin ('{self.provider_id}'): Max retries ({self.retry_count + 1}) exhausted for {method_name}. Last error: {e}", exc_info=True)
                    raise NetworkPluginError(provider_id=self.provider_id, message=f"API call {method_name} failed after retries: {e}", original_exception=e) from e
                delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.2)
                logger.warning(f"CryptoPlugin ('{self.provider_id}'): {type(e).__name__} on {method_name} (Attempt {attempt+1}/{self.retry_count+1}). Retrying in {delay:.2f}s. Error: {str(e)[:150]}")
                await asyncio.sleep(delay)
            except CCXTAuthenticationError as e:
                raise AuthenticationPluginError(provider_id=self.provider_id, original_exception=e) from e
            except CCXTBadSymbol as e:
                 raise PluginError(message=f"Invalid symbol for {method_name}: {e}", provider_id=self.provider_id, original_exception=e) from e
            except CCXTNotSupported as e:
                raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, method_name) from e
            except CCXTExchangeError as e:
                raise PluginError(message=f"Exchange error during {method_name}: {e}", provider_id=self.provider_id, original_exception=e) from e
            except Exception as e: # Catch any other unexpected errors (like TypeError if args are wrong for underlying call)
                logger.error(f"CryptoPlugin ('{self.provider_id}'): Unexpected error in {method_name} (Args: {args}, Kwargs: {kwargs}): {e}", exc_info=True)
                last_exception = e
                if attempt == self.retry_count:
                    raise PluginError(message=f"API call {method_name} failed due to unexpected error: {e}", provider_id=self.provider_id, original_exception=e) from e
                delay = self.retry_delay_base * (2 ** attempt)
                await asyncio.sleep(delay)
        
        if last_exception:
            raise PluginError(message=f"Retry loop for {method_name} exhausted. Last error: {last_exception}", provider_id=self.provider_id, original_exception=last_exception)
        raise PluginError(message=f"Exited retry loop unexpectedly for {method_name}. This indicates a logic flaw.", provider_id=self.provider_id)



    async def _load_and_cache_markets(self, reload: bool = False) -> Dict[str, Any]:
        """
        Helper to load market data from CCXT and cache it at the CryptoPlugin instance level.
        Uses a simple time-based expiry for the instance cache.
        """
        current_time = time.monotonic()
        if not reload and self._all_markets_data and \
           (current_time - self._all_markets_timestamp < MARKET_CACHE_TTL_SECONDS):
            logger.debug(f"CryptoPlugin (Instance for '{self.provider_id}'): Returning all markets data from instance cache.")
            return self._all_markets_data

        logger.debug(f"CryptoPlugin (Instance for '{self.provider_id}'): Loading/Reloading all markets data from exchange (reload={reload}).")
        try:
            markets_data = await self._call_ccxt_method('load_markets', reload=reload) # Pass reload as a direct argument
            if isinstance(markets_data, dict):
                self._all_markets_data = markets_data
                self._all_markets_timestamp = current_time
                logger.info(f"CryptoPlugin (Instance for '{self.provider_id}'): Successfully loaded and cached {len(self._all_markets_data)} markets.")
                return self._all_markets_data
            else:
                logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): load_markets returned non-dict type: {type(markets_data)}. Returning empty.")
                self._all_markets_data = {} # Cache empty dict on failure
                self._all_markets_timestamp = current_time
                return {}
        except PluginError as e: # Catch errors from _call_ccxt_method
            logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): Failed to load markets: {e.args[0] if e.args else str(e)}")
             # Optionally, re-raise or return empty/stale cache
            if self._all_markets_data and not reload: # Return stale if available and not forcing reload
                logger.warning(f"CryptoPlugin (Instance for '{self.provider_id}'): Returning stale market data due to load failure.")
                return self._all_markets_data
            self._all_markets_data = {} # Cache empty on error if no stale data
            self._all_markets_timestamp = current_time
            raise # Re-raise the PluginError to signal failure to caller
            
    # --- MarketPlugin ABC Implementation ---

    async def get_symbols(self) -> List[str]:
        """
        Fetches the list of tradable symbols from the configured CCXT exchange instance (`self.provider_id`).
        Filters for active spot markets by default, with fallbacks.
        """
        # Note: CCXT's load_markets is the source of symbols. Results are cached by _load_and_cache_markets.
        logger.debug(f"CryptoPlugin (Instance for '{self.provider_id}'): Getting symbols.")
        try:
            markets_data = await self._load_and_cache_markets() # Ensures markets are loaded
            
            symbols_list: List[str] = []
            if markets_data:
                # Prioritize active spot symbols
                symbols_list = [
                    market_info['symbol'] for market_info in markets_data.values()
                    if market_info.get('active', True) and market_info.get('type') == 'spot'
                ]
                if not symbols_list: # Fallback 1: Any active market
                    logger.warning(f"CryptoPlugin (Instance for '{self.provider_id}'): No active 'spot' symbols. Falling back to any active market type.")
                    symbols_list = [
                        market_info['symbol'] for market_info in markets_data.values()
                        if market_info.get('active', True)
                    ]
                if not symbols_list: # Fallback 2: All symbols if no active ones
                     logger.warning(f"CryptoPlugin (Instance for '{self.provider_id}'): No active symbols of any type. Falling back to all symbols.")
                     symbols_list = list(markets_data.keys())
            else:
                 logger.warning(f"CryptoPlugin (Instance for '{self.provider_id}'): No market data available to extract symbols.")
            
            logger.info(f"CryptoPlugin (Instance for '{self.provider_id}'): Returning {len(symbols_list)} symbols.")
            return sorted(symbols_list)
        except PluginError: # Re-raise from _load_and_cache_markets
            raise
        except Exception as e: # Catch-all for other unexpected errors
            logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): Unexpected error in get_symbols: {e}", exc_info=True)
            raise PluginError(message=f"Could not get symbols: {e}", provider_id=self.provider_id, original_exception=e) from e

    def _normalize_timeframe_for_ccxt(self, timeframe: str) -> str:
        """
        Normalizes a timeframe string to a common CCXT-compatible format.
        e.g., "1D" -> "1d", "1W" -> "1w", "1MON" -> "1M".
        CCXT typically uses lowercase for d, h, m, s and uppercase M for month, Y for year.
        This function aims to bridge common variations if your internal standard differs.
        If your internal standard is already CCXT-like (e.g. "1m", "1h", "1d", "1w", "1M"),
        this function might just do minor case adjustments or pass through.
        """
        # Assuming your internal standard might be like "1H", "1D" and CCXT prefers "1h", "1d"
        # and "1MON" for month.
        tf_lower = timeframe.lower()
        if tf_lower.endswith('d'): return tf_lower[:-1] + 'd' # 1D -> 1d
        if tf_lower.endswith('h'): return tf_lower[:-1] + 'h' # 1H -> 1h
        if tf_lower.endswith('w'): return tf_lower[:-1] + 'w' # 1W -> 1w
        if tf_lower.endswith('mon'): return tf_lower[:-3] + 'M' # 1MON -> 1M
        if tf_lower.endswith('y'): return tf_lower[:-1] + 'y' # 1Y -> 1y (or Y, CCXT handles)
        # m for minute is usually fine.
        # This is a simplified example; a more robust one would use regex like in utils.timeframes
        # For now, if the internal standard is close to CCXT, this might suffice.
        # CCXT itself is quite good at parsing common variations.
        return timeframe # Pass through if no specific rule matches

    async def fetch_historical_ohlcv(
        self, symbol: str, timeframe: str,
        since: Optional[int] = None, limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> List[OHLCVBar]:
        """Fetches historical OHLCV data from the configured CCXT exchange instance."""
        
        # Convert internal standard timeframe to one CCXT typically understands
        ccxt_timeframe = self._normalize_timeframe_for_ccxt(timeframe)
        
        final_params = params.copy() if params else {}
        # `until` is a common parameter for CCXT that might be passed in `params`
        # Ensure `until` is also in milliseconds if present.

        logger.debug(
            f"CryptoPlugin (Instance for '{self.provider_id}'): Fetching OHLCV. Symbol: {symbol}, "
            f"Requested TF: {timeframe} (CCXT TF: {ccxt_timeframe}), "
            f"Since: {format_timestamp_to_iso(since) if since else 'N/A'}, Limit: {limit}, API Params: {final_params}"
        )

        raw_ohlcv_data = await self._call_ccxt_method('fetch_ohlcv', symbol, ccxt_timeframe, since, limit, params=final_params)
            
        parsed_bars: List[OHLCVBar] = []
        if raw_ohlcv_data and isinstance(raw_ohlcv_data, list):
            for i, bar_data in enumerate(raw_ohlcv_data):
                try:
                    if not (isinstance(bar_data, list) and len(bar_data) >= 6):
                        logger.warning(f"CryptoPlugin ('{self.provider_id}'): Malformed bar data for {symbol} at index {i}: {bar_data}. Skipping.")
                        continue
                    
                    # CCXT standard: [timestamp, open, high, low, close, volume]
                    # Ensure all numeric fields are present and correctly typed.
                    ts, o, h, l, c, v = bar_data[0], bar_data[1], bar_data[2], bar_data[3], bar_data[4], bar_data[5]
                    if not all(isinstance(val, (int, float)) for val in [ts, o, h, l, c]) or \
                       not isinstance(v, (int, float, type(None))): # Volume can be None
                        logger.warning(f"CryptoPlugin ('{self.provider_id}'): Type mismatch in bar data for {symbol} at index {i}: {bar_data}. Skipping.")
                        continue

                    parsed_bars.append({
                        "timestamp": int(ts), "open": float(o),
                        "high": float(h), "low": float(l),
                        "close": float(c), "volume": float(v) if v is not None else 0.0,
                    })
                except (IndexError, TypeError, ValueError) as e_parse:
                    logger.warning(f"CryptoPlugin ('{self.provider_id}'): Error parsing raw bar for {symbol} idx {i}: {bar_data}. Error: {e_parse}. Skipping.", exc_info=False)
                    continue
        
        logger.info(f"CryptoPlugin (Instance for '{self.provider_id}'): Fetched {len(parsed_bars)} OHLCV bars for {symbol}/{ccxt_timeframe}.")
        # CCXT generally returns bars sorted oldest to newest. If not, sorting here would be needed.
        # parsed_bars.sort(key=lambda b: b['timestamp'])
        return parsed_bars

    async def fetch_latest_ohlcv(self, symbol: str, timeframe: str = "1m") -> Optional[OHLCVBar]:
        """
        Fetches the most recent OHLCV bar using `Workspace_historical_ohlcv` with a small limit.
        Note: CCXT fetchOHLCV with limit=1 might not always give the absolute latest *partial* bar,
        but rather the last *completed* bar depending on the exchange.
        """
        logger.debug(f"CryptoPlugin (Instance for '{self.provider_id}'): Fetching latest '{timeframe}' bar for {symbol}.")
        try:
            # Fetch 2 bars and take the last one to increase chances of getting the most recent completed one.
            # Some exchanges might return an empty list if 'since' is too recent for a full bar.
            # Not setting 'since' to get the absolute latest bars up to `limit`.
            bars = await self.fetch_historical_ohlcv(symbol=symbol, timeframe=timeframe, limit=2, params={})
            
            if bars:
                latest_bar = bars[-1] # The last bar in the list is the most recent.
                logger.info(
                    f"CryptoPlugin (Instance for '{self.provider_id}'): Fetched latest '{timeframe}' bar for {symbol} "
                    f"@ {format_timestamp_to_iso(latest_bar['timestamp'])}"
                )
                return latest_bar
            
            logger.warning(f"CryptoPlugin (Instance for '{self.provider_id}'): No latest '{timeframe}' bar returned by fetch_historical_ohlcv for {symbol}.")
            return None
        except PluginError as e: 
            logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): PluginError fetching latest OHLCV for {symbol}/{timeframe}: {e.args[0] if e.args else str(e)}", exc_info=False) 
            return None 
        except Exception as e: 
            logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): Unexpected error fetching latest OHLCV for {symbol}/{timeframe}: {e}", exc_info=True)
            return None

    # --- Optional Utility / Metadata Methods ---

    async def get_market_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieves detailed market information for a specific symbol from the CCXT exchange instance."""
        logger.debug(f"CryptoPlugin (Instance for '{self.provider_id}'): Getting market info for '{symbol}'.")
        try:
            all_markets_data = await self._load_and_cache_markets() # Ensures all markets are loaded
            market_data = all_markets_data.get(symbol)
            
            if market_data:
                logger.info(f"CryptoPlugin (Instance for '{self.provider_id}'): Found market info for '{symbol}'.")
                return market_data # Return the raw market object from CCXT
            
            logger.warning(f"CryptoPlugin (Instance for '{self.provider_id}'): No market info found for symbol '{symbol}'.")
            return None
        except PluginError: # Re-raise from _load_and_cache_markets or _call_ccxt_method
            raise
        except Exception as e: 
            logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): Error fetching market info for '{symbol}': {e}", exc_info=True)
            raise PluginError(message=f"Could not get market info for {symbol}: {e}", provider_id=self.provider_id, original_exception=e) from e

    async def validate_symbol(self, symbol: str) -> bool:
        """Validates if a symbol is recognized and active on the CCXT exchange instance."""
        logger.debug(f"CryptoPlugin (Instance for '{self.provider_id}'): Validating symbol '{symbol}'.")
        try:
            market_info = await self.get_market_info(symbol) # Uses cached all_markets_data
            is_valid = market_info is not None and market_info.get('active', True) # Default to active if key missing
            logger.debug(f"CryptoPlugin (Instance for '{self.provider_id}'): Symbol '{symbol}' validation result: {is_valid} (Active: {market_info.get('active') if market_info else 'N/A'})")
            return is_valid
        except PluginError: # Catches errors from get_market_info (like if markets fail to load)
            return False # If we can't get market info, assume symbol is not valid for safety
        except Exception: 
            logger.exception(f"CryptoPlugin (Instance for '{self.provider_id}'): Unexpected error during validate_symbol for '{symbol}'. Assuming invalid.")
            return False

    async def get_supported_timeframes(self) -> Optional[List[str]]:
        """Gets supported timeframes from the CCXT exchange object. Uses instance cache."""
        if self._supported_timeframes is not None:
            return self._supported_timeframes
        try:
            exchange = await self._get_exchange()
            if hasattr(exchange, 'timeframes') and exchange.timeframes and isinstance(exchange.timeframes, dict):
                self._supported_timeframes = sorted(list(exchange.timeframes.keys()))
                logger.info(f"CryptoPlugin (Instance for '{self.provider_id}'): Supported timeframes loaded: {self._supported_timeframes}")
                return self._supported_timeframes
            
            logger.warning(f"CryptoPlugin (Instance for '{self.provider_id}'): Exchange does not list timeframes via 'exchange.timeframes' or it's empty/invalid.")
            self._supported_timeframes = [] 
            return None
        except Exception as e:
            logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): Error fetching supported timeframes: {e}", exc_info=True)
            self._supported_timeframes = [] 
            return None

    async def get_fetch_ohlcv_limit(self) -> int:
        """
        Gets the OHLCV fetch limit from the CCXT exchange object. Uses instance cache.
        Defaults to a common value (e.g., 1000) if not specified by CCXT.
        """
        if self._fetch_limit is not None: 
            return self._fetch_limit
        
        default_limit = 1000 # A common safe default
        try:
            exchange = await self._get_exchange()
            limit = default_limit
            # Standard CCXT way to get limits
            if hasattr(exchange, 'limits') and isinstance(exchange.limits, dict) and \
               'OHLCV' in exchange.limits and isinstance(exchange.limits['OHLCV'], dict) and \
               'max' in exchange.limits['OHLCV'] and isinstance(exchange.limits['OHLCV']['max'], int):
                limit = exchange.limits['OHLCV']['max']
            # Fallback for some older CCXT versions or specific exchange structures
            elif hasattr(exchange, 'options') and isinstance(exchange.options, dict) and \
                 'fetchOHLCVLimit' in exchange.options and isinstance(exchange.options['fetchOHLCVLimit'], int):
                limit = exchange.options['fetchOHLCVLimit']
            elif hasattr(exchange, 'fetchOHLCVLimit') and isinstance(getattr(exchange, 'fetchOHLCVLimit', None), int):
                 limit = getattr(exchange, 'fetchOHLCVLimit') # type: ignore
            
            self._fetch_limit = max(1, limit) if limit > 0 else default_limit
            logger.info(f"CryptoPlugin (Instance for '{self.provider_id}'): Determined fetchOHLCV limit: {self._fetch_limit}.")
            return self._fetch_limit
        except Exception as e:
            logger.warning(f"CryptoPlugin (Instance for '{self.provider_id}'): Error determining fetchOHLCV limit: {e}. Defaulting to {default_limit}.", exc_info=False)
            self._fetch_limit = default_limit 
            return default_limit
            
    async def get_supported_features(self) -> Dict[str, bool]:
        """Declare features supported by this CryptoPlugin instance (depends on the CCXT exchange)."""
        exchange = await self._get_exchange() # Ensure exchange is initialized
        return {
            "watch_ticks": exchange.has.get('watchTicker', False) or exchange.has.get('watchTickers', False),
            "fetch_trades": exchange.has.get('fetchTrades', False),
            "trading_api": exchange.has.get('createOrder', False) and exchange.has.get('fetchBalance', False), # Basic check
            "get_market_info": True, # Implemented via load_markets
            "validate_symbol": True, # Implemented via load_markets
            "get_supported_timeframes": True, # Implemented
            "get_fetch_ohlcv_limit": True, # Implemented
        }

    async def close(self) -> None:
        """Closes the CCXT exchange connection for this instance and clears instance caches."""
        logger.info(
            f"CryptoPlugin (Instance for '{self.provider_id}'): Closing. Testnet: {self.is_testnet}, API Key Used: {bool(self.api_key)}"
        )
        async with self._exchange_lock: # Ensure exclusive access during close
            if self._exchange:
                if hasattr(self._exchange, 'close') and callable(self._exchange.close):
                    try:
                        if asyncio.iscoroutinefunction(self._exchange.close):
                            await self._exchange.close()
                        else:
                            self._exchange.close() # type: ignore
                        logger.info(f"CryptoPlugin (Instance for '{self.provider_id}'): CCXT exchange connection closed.")
                    except Exception as e:
                        logger.error(f"CryptoPlugin (Instance for '{self.provider_id}'): Error closing CCXT connection: {e}", exc_info=True)
                self._exchange = None # Dereference the exchange object

        # Clear all instance-specific caches
        self._all_markets_data = None
        self._all_markets_timestamp = 0.0
        self._supported_timeframes = None
        self._fetch_limit = None
        logger.info(f"CryptoPlugin (Instance for '{self.provider_id}'): Instance-specific caches cleared.")