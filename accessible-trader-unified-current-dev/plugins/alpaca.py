# plugins/alpaca.py

import asyncio
import logging
import os
import time 
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp 

# Updated imports from plugins.base
from plugins.base import (
    MarketPlugin,
    PluginError,
    AuthenticationPluginError,
    NetworkPluginError,
    PluginFeatureNotSupportedError,
    OHLCVBar,
    # NEW TypedDicts for trading operations and instrument details
    Order,
    Position,
    Balance,
    InstrumentTradingDetails,
    Precision,      # Component of InstrumentTradingDetails
    MarketLimits,   # Component of InstrumentTradingDetails
    MarginTradingDetails # Component of InstrumentTradingDetails
)

logger = logging.getLogger(__name__)

ALPACA_BASE_URL_PAPER = "https://paper-api.alpaca.markets"
ALPACA_BASE_URL_LIVE = "https://api.alpaca.markets"
ALPACA_DATA_URL = "https://data.alpaca.markets"

class AlpacaPlugin(MarketPlugin):
    plugin_key: str = "alpaca"
    supported_markets: List[str] = ["us_equity"]

    def __init__(
        self,
        provider_id: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None, # Alpaca doesn't use this, but keep for base class signature
        is_testnet: bool = False,
        request_timeout: int = 30000,
        verbose_logging: bool = False,
        **kwargs: Any
    ):
        if provider_id.lower() != "alpaca":
            raise PluginError(
                message=f"AlpacaPlugin initialized with incorrect provider_id: '{provider_id}'. Expected 'alpaca'.",
                provider_id=provider_id
            )

        super().__init__(
            provider_id="alpaca",
            api_key=api_key or os.getenv("ALPACA_API_KEY"),
            api_secret=api_secret or os.getenv("ALPACA_API_SECRET"),
            api_passphrase=api_passphrase, # Will be None for Alpaca
            is_testnet=is_testnet,
            request_timeout=request_timeout,
            verbose_logging=verbose_logging,
            **kwargs
        )

        self._base_url_trading_api = ALPACA_BASE_URL_PAPER if self.is_testnet else ALPACA_BASE_URL_LIVE
        self._base_url_data_api = ALPACA_DATA_URL

        self._session_data: Optional[aiohttp.ClientSession] = None
        self._session_trading: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()

        self._validate_symbol_cache: Dict[str, bool] = {}
        self._market_info_cache: Dict[str, Dict[str, Any]] = {}
        self._supported_timeframes_cache: Optional[List[str]] = None
        self._fetch_limit_cache: Optional[int] = None
        
        self._assets_cache: Tuple[Optional[List[Dict[str, Any]]], float] = (None, 0.0)
        self._assets_cache_ttl_seconds = 3600

        if not self.api_key or not self.api_secret:
            logger.warning(
                f"AlpacaPlugin for '{self.provider_id}' initialized without API Key ID or Secret Key. "
                "Operations requiring authentication will fail."
            )
        # Updated logger to match base class's __init__ debug log format for consistency
        logger.info(
            f"AlpacaPlugin instance (class_key: '{self.plugin_key}') initialized for Provider ID: '{self.provider_id}'. "
            f"Testnet (Paper): {self.is_testnet}, API Key Provided: {bool(self.api_key)}, Passphrase Provided: {bool(self.api_passphrase)}."
        )

    @classmethod
    def get_plugin_key(cls) -> str:
        return cls.plugin_key

    @classmethod
    def get_supported_markets(cls) -> List[str]:
        return cls.supported_markets

    @classmethod
    def list_configurable_providers(cls) -> List[str]:
        return ["alpaca"]

    async def _get_auth_headers(self) -> Dict[str, str]:
        if not self.api_key or not self.api_secret:
            raise AuthenticationPluginError(
                provider_id=self.provider_id,
                message="API Key ID and Secret Key are required for this Alpaca API operation."
            )
        return {"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.api_secret}

    async def _get_data_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session_data is None or self._session_data.closed:
                headers = await self._get_auth_headers()
                timeout = aiohttp.ClientTimeout(total=self.request_timeout / 1000.0)
                self._session_data = aiohttp.ClientSession(headers=headers, timeout=timeout)
            return self._session_data

    async def _get_trading_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session_trading is None or self._session_trading.closed:
                headers = await self._get_auth_headers()
                timeout = aiohttp.ClientTimeout(total=self.request_timeout / 1000.0)
                self._session_trading = aiohttp.ClientSession(headers=headers, timeout=timeout)
            return self._session_trading

    async def _request_api(self, session_type: str, endpoint: str, params: Optional[Dict[str, Any]] = None, method: str = "GET", json_payload: Optional[Dict[str, Any]] = None) -> Any:
        session = await self._get_data_session() if session_type == "data" else await self._get_trading_session()
        base_url = self._base_url_data_api if session_type == "data" else self._base_url_trading_api
        url = f"{base_url}{endpoint}"
        response_text_snippet = ""
        
        request_args = {"params": params}
        if json_payload is not None and method.upper() in ["POST", "PUT", "PATCH"]:
            request_args["json"] = json_payload
            del request_args["params"] # Typically don't send params if json body is present for POST/PUT

        try:
            if self.verbose_logging: logger.debug(f"AlpacaPlugin '{self.provider_id}': Requesting {method} {url}, Args: {request_args}")
            async with session.request(method, url, **request_args) as response:
                response_text = await response.text()
                response_text_snippet = response_text[:500]
                if self.verbose_logging: logger.debug(f"AlpacaPlugin '{self.provider_id}': Response status {response.status} from {url}. Snippet: {response_text_snippet}")
                
                if response.status == 401 or response.status == 403: raise AuthenticationPluginError(self.provider_id, f"API Error {response.status}: {response_text_snippet}")
                if response.status == 429: raise NetworkPluginError(self.provider_id, f"API Error 429 (Rate Limit): {response_text_snippet}")
                if response.status == 404: raise PluginError(self.provider_id, f"API Error 404 (Not Found) for {url}: {response_text_snippet}")
                # Alpaca uses 422 for unprocessable entity (e.g. bad order params)
                if response.status == 422: raise PluginError(self.provider_id, f"API Error 422 (Unprocessable Entity): {response_text_snippet}", original_exception=aiohttp.ClientResponseError(response.request_info, response.history, status=response.status, message=response_text_snippet))

                response.raise_for_status() # For other 4xx/5xx errors
                return {} if response.status == 204 else await response.json(content_type=None) # Handle 204 No Content
        except aiohttp.ClientResponseError as e:
            # This catches errors from response.raise_for_status() if not already handled
            logger.error(f"AlpacaPlugin '{self.provider_id}': HTTP error {e.status} for {url}: {e.message}. Response: {response_text_snippet}", exc_info=False)
            raise PluginError(f"HTTP error {e.status}: {e.message}", self.provider_id, e) from e
        except asyncio.TimeoutError as e:
            logger.error(f"AlpacaPlugin '{self.provider_id}': Request timeout for {url}: {e}", exc_info=True)
            raise NetworkPluginError(self.provider_id, "Request timed out", e) from e
        except aiohttp.ClientError as e: # Includes ClientConnectorError, ServerDisconnectedError, etc.
            logger.error(f"AlpacaPlugin '{self.provider_id}': Client error for {url}: {e}", exc_info=True)
            raise NetworkPluginError(self.provider_id, f"Client connection error: {e}", e) from e
        except Exception as e: # Catch-all for other unexpected errors
            logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error for {url}: {e}. Snippet: {response_text_snippet}", exc_info=True)
            raise PluginError(f"Unexpected API error: {e}", self.provider_id, e) from e

    def _map_to_alpaca_timeframe(self, internal_timeframe: str) -> str:
        # ... (your existing implementation) ...
        mapping = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1h": "1Hour", "1H": "1Hour", "1d": "1Day", "1D": "1Day"}
        alpaca_tf = mapping.get(internal_timeframe, internal_timeframe)
        if alpaca_tf == internal_timeframe and internal_timeframe not in mapping.values():
            logger.warning(f"AlpacaPlugin '{self.provider_id}': Timeframe '{internal_timeframe}' has no direct Alpaca mapping. Passing as is.")
        return alpaca_tf

    async def get_symbols(self, market: str) -> List[str]:
        # ... (your existing implementation) ...
        logger.debug(f"AlpacaPlugin '{self.provider_id}': get_symbols requested for market '{market}'.")
        normalized_market = market.lower()
        if normalized_market != "us_equity":
            msg = f"AlpacaPlugin only supports 'us_equity' market for get_symbols, not '{market}'."
            logger.error(f"AlpacaPlugin '{self.provider_id}': {msg}")
            raise PluginError(message=msg, provider_id=self.provider_id)
        asset_class_for_api = "us_equity"
        current_time = time.monotonic()
        cached_assets_data, cache_timestamp = self._assets_cache
        if cached_assets_data and (current_time - cache_timestamp < self._assets_cache_ttl_seconds):
            logger.debug(f"AlpacaPlugin '{self.provider_id}': Returning 'us_equity' assets from cache.")
            assets_response_data = cached_assets_data
        else:
            logger.debug(f"AlpacaPlugin '{self.provider_id}': Fetching 'us_equity' assets from API.")
            api_request_params = {"status": "active", "asset_class": asset_class_for_api, "tradable": "true"}
            try:
                assets_response_data = await self._request_api("trading", "/v2/assets", params=api_request_params)
                if isinstance(assets_response_data, list):
                    self._assets_cache = (assets_response_data, current_time)
                else:
                    logger.warning(f"AlpacaPlugin '{self.provider_id}': /v2/assets did not return a list. Type: {type(assets_response_data)}")
                    assets_response_data = []
            except PluginError as e: 
                logger.error(f"AlpacaPlugin '{self.provider_id}': PluginError fetching 'us_equity' assets: {e}", exc_info=False)
                if cached_assets_data: 
                    logger.warning(f"AlpacaPlugin '{self.provider_id}': Returning stale 'us_equity' asset list due to fetch error.")
                    assets_response_data = cached_assets_data
                else:
                    raise
            except Exception as e:
                logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error fetching 'us_equity' assets: {e}", exc_info=True)
                if cached_assets_data:
                    logger.warning(f"AlpacaPlugin '{self.provider_id}': Returning stale 'us_equity' asset list due to unexpected error.")
                    assets_response_data = cached_assets_data
                else:
                    raise PluginError(f"Unexpected error fetching assets: {e}", self.provider_id, e) from e
        symbols: List[str] = []
        if isinstance(assets_response_data, list):
            for asset in assets_response_data:
                if isinstance(asset, dict) and asset.get("symbol") and asset.get("tradable"):
                    symbols.append(asset["symbol"])
        else:
            logger.warning(f"AlpacaPlugin '{self.provider_id}': assets_response_data is not a list for 'us_equity'. Type: {type(assets_response_data)}")
        logger.info(f"AlpacaPlugin '{self.provider_id}': Fetched {len(symbols)} symbols for market 'us_equity'.")
        return sorted(symbols)

    async def fetch_historical_ohlcv(self, symbol: str, timeframe: str, since: Optional[int] = None, limit: Optional[int] = None, params: Optional[Dict[str, Any]] = None) -> List[OHLCVBar]:
        # ... (your existing implementation) ...
        alpaca_tf = self._map_to_alpaca_timeframe(timeframe)
        endpoint = f"/v2/stocks/{symbol}/bars"
        max_limit_plugin = await self.get_fetch_ohlcv_limit() 
        api_params: Dict[str, Any] = {"timeframe": alpaca_tf, "adjustment": "raw"}
        if limit is not None:
            api_params["limit"] = min(limit, max_limit_plugin)
        else:
            api_params["limit"] = max_limit_plugin
        if since is not None:
            api_params["start"] = datetime.fromtimestamp(since / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        if params and params.get("until_ms"):
            api_params["end"] = datetime.fromtimestamp(params["until_ms"] / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        elif params and params.get("end"): 
            api_params["end"] = params["end"]
        logger.debug(f"AlpacaPlugin '{self.provider_id}': Fetching historical OHLCV from {endpoint} for '{symbol}' (us_equity) @ {alpaca_tf}. API Params: {api_params}")
        try:
            response_data = await self._request_api("data", endpoint, params=api_params)
            parsed_bars: List[OHLCVBar] = []
            if response_data and "bars" in response_data and isinstance(response_data["bars"], list):
                for bar_data in response_data["bars"]:
                    try:
                        ts_str = bar_data.get("t")
                        if not ts_str: continue
                        dt_obj = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        timestamp_ms = int(dt_obj.timestamp() * 1000)
                        parsed_bars.append({"timestamp": timestamp_ms, "open": float(bar_data["o"]), "high": float(bar_data["h"]), "low": float(bar_data["l"]), "close": float(bar_data["c"]), "volume": float(bar_data["v"])})
                    except (KeyError, TypeError, ValueError) as e_parse:
                        logger.warning(f"AlpacaPlugin '{self.provider_id}': Error parsing bar for {symbol}: {bar_data}. Error: {e_parse}. Skipping.", exc_info=False)
            logger.info(f"AlpacaPlugin '{self.provider_id}': Fetched {len(parsed_bars)} OHLCV bars for {symbol}/{timeframe} (us_equity).")
            return parsed_bars
        except PluginError: raise
        except Exception as e:
            logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error in fetch_historical_ohlcv for {symbol} (us_equity): {e}", exc_info=True)
            raise PluginError(f"Unexpected error fetching OHLCV: {e}", self.provider_id, e) from e

    async def fetch_latest_ohlcv(self, symbol: str, timeframe: str = "1m") -> Optional[OHLCVBar]:
        # ... (your existing implementation, ensure it's robust) ...
        logger.debug(f"AlpacaPlugin '{self.provider_id}': Fetching latest '{timeframe}' bar for '{symbol}' (us_equity).")
        alpaca_tf_for_latest = self._map_to_alpaca_timeframe(timeframe)
        if alpaca_tf_for_latest in ["1Min", "1Day"]:
            endpoint = f"/v2/stocks/{symbol}/bars/latest"
            api_params = {"timeframe": alpaca_tf_for_latest} 
            logger.debug(f"AlpacaPlugin '{self.provider_id}': Using latest bar endpoint: {endpoint} with params: {api_params}")
            try:
                response_data = await self._request_api("data", endpoint, params=api_params)
                bar_data_key = "bar" 
                if response_data and bar_data_key in response_data and isinstance(response_data[bar_data_key], dict):
                    bar_data = response_data[bar_data_key]
                    ts_str = bar_data.get("t")
                    if not ts_str: return None
                    dt_obj = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    timestamp_ms = int(dt_obj.timestamp() * 1000)
                    latest_bar: OHLCVBar = {"timestamp": timestamp_ms, "open": float(bar_data["o"]), "high": float(bar_data["h"]), "low": float(bar_data["l"]), "close": float(bar_data["c"]), "volume": float(bar_data["v"])}
                    logger.info(f"AlpacaPlugin '{self.provider_id}': Fetched latest '{timeframe}' bar for {symbol} (us_equity) via latest endpoint.")
                    return latest_bar
                logger.warning(f"AlpacaPlugin '{self.provider_id}': No latest bar data in response for {symbol} (us_equity) from /latest endpoint.")
            except PluginError as e:
                logger.warning(f"AlpacaPlugin '{self.provider_id}': PluginError with /latest endpoint for {symbol}/{timeframe}: {e}. Will attempt fallback.")
            except Exception as e:
                logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error with /latest endpoint for {symbol}/{timeframe}: {e}", exc_info=True)
        logger.debug(f"AlpacaPlugin '{self.provider_id}': Using historical fetch as fallback/default for latest '{timeframe}' bar for {symbol} (us_equity).")
        try:
            bars = await self.fetch_historical_ohlcv(symbol=symbol, timeframe=timeframe, limit=2) 
            if bars:
                latest_bar = bars[-1]
                logger.info(f"AlpacaPlugin '{self.provider_id}': Fetched latest '{timeframe}' bar for {symbol} (us_equity) via historical fallback.")
                return latest_bar
            logger.warning(f"AlpacaPlugin '{self.provider_id}': No latest '{timeframe}' bar for {symbol} (us_equity) from historical fallback.")
            return None
        except PluginError as e:
            logger.error(f"AlpacaPlugin '{self.provider_id}': PluginError during fallback latest bar fetch for {symbol}/{timeframe} (us_equity): {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error during fallback latest bar fetch for {symbol}/{timeframe} (us_equity): {e}", exc_info=True)
            return None

    async def get_market_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        # ... (your existing implementation) ...
        cache_entry = self._market_info_cache.get(symbol)
        current_time = time.monotonic()
        MARKET_INFO_TTL_SECONDS = 3600
        if cache_entry and (current_time - cache_entry.get('timestamp', 0) < MARKET_INFO_TTL_SECONDS):
            return cache_entry.get('data')
        logger.debug(f"AlpacaPlugin '{self.provider_id}': Fetching market info (asset details) for '{symbol}' (assumed us_equity).")
        try:
            asset_data = await self._request_api("trading", f"/v2/assets/{symbol}")
            if asset_data and isinstance(asset_data, dict):
                if asset_data.get("asset_class") != "us_equity":
                    logger.warning(f"AlpacaPlugin '{self.provider_id}': Fetched market info for '{symbol}', but its asset_class is '{asset_data.get('asset_class')}', not 'us_equity'. Plugin is specialized for us_equity.")
                    self._market_info_cache[symbol] = {'data': None, 'timestamp': current_time} 
                    return None
                self._market_info_cache[symbol] = {'data': asset_data, 'timestamp': current_time}
                logger.info(f"AlpacaPlugin '{self.provider_id}': Fetched and cached market info for '{symbol}'.")
                return asset_data
            logger.warning(f"AlpacaPlugin '{self.provider_id}': No market info returned or unexpected format for '{symbol}'.")
            self._market_info_cache[symbol] = {'data': None, 'timestamp': current_time}
            return None
        except PluginError as e:
            if "404 (Not Found)" in str(e) or (hasattr(e.original_exception, 'status') and e.original_exception.status == 404):
                logger.info(f"AlpacaPlugin '{self.provider_id}': Market info not found for symbol '{symbol}' (Alpaca API 404).")
                self._market_info_cache[symbol] = {'data': None, 'timestamp': current_time}
                return None
            logger.error(f"AlpacaPlugin '{self.provider_id}': PluginError fetching market info for '{symbol}': {e}", exc_info=False)
            raise
        except Exception as e:
            logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error fetching market info for '{symbol}': {e}", exc_info=True)
            raise PluginError(f"Unexpected error fetching market info for {symbol}: {e}", self.provider_id, e) from e

    async def validate_symbol(self, symbol: str) -> bool:
        # ... (your existing implementation) ...
        if symbol in self._validate_symbol_cache:
            return self._validate_symbol_cache[symbol]
        logger.debug(f"AlpacaPlugin '{self.provider_id}': Validating symbol '{symbol}' (as us_equity).")
        try:
            asset_info = await self.get_market_info(symbol) 
            is_valid = False
            if asset_info: 
                is_valid = asset_info.get('tradable', False) and asset_info.get('status') == 'active' 
                if not is_valid:
                    logger.info(f"AlpacaPlugin '{self.provider_id}': Symbol '{symbol}' found but not active/tradable. Tradable: {asset_info.get('tradable')}, Status: {asset_info.get('status')}.")
            else:
                logger.info(f"AlpacaPlugin '{self.provider_id}': Symbol '{symbol}' not found or not 'us_equity' during validation.")
            self._validate_symbol_cache[symbol] = is_valid
            return is_valid
        except AuthenticationPluginError: 
            logger.warning(f"AlpacaPlugin '{self.provider_id}': Cannot validate symbol '{symbol}' without API keys (get_market_info requires auth). Assuming invalid.")
            self._validate_symbol_cache[symbol] = False
            return False 
        except PluginError: 
            logger.warning(f"AlpacaPlugin '{self.provider_id}': PluginError during get_market_info for validation of '{symbol}'. Assuming invalid.")
            self._validate_symbol_cache[symbol] = False
            return False
        except Exception: 
            logger.exception(f"AlpacaPlugin '{self.provider_id}'): Unexpected error during validate_symbol for '{symbol}'. Assuming invalid.")
            self._validate_symbol_cache[symbol] = False
            return False

    async def get_supported_timeframes(self) -> Optional[List[str]]:
        # ... (your existing implementation) ...
        if self._supported_timeframes_cache is None:
            self._supported_timeframes_cache = ["1m", "5m", "15m", "30m", "1h", "1H", "1d", "1D"]
        return self._supported_timeframes_cache

    async def get_fetch_ohlcv_limit(self) -> int:
        # ... (your existing implementation) ...
        if self._fetch_limit_cache is None:
            self._fetch_limit_cache = 10000 
        return self._fetch_limit_cache
        
    # --- <<< NEW/Updated Methods for Trading and Form Details >>> ---

    async def get_instrument_trading_details(
        self,
        symbol: str,
        market_type: Optional[str] = 'spot' # Alpaca mainly 'spot' for stocks/ETFs via this API
    ) -> InstrumentTradingDetails:
        """
        Fetches detailed trading rules and parameters for a specific stock/ETF symbol from Alpaca.
        """
        log_context = f"{self.provider_id}/{symbol}/{market_type}"
        logger.debug(f"AlpacaPlugin: Getting instrument trading details for {log_context}")

        if market_type != 'spot':
             logger.warning(f"AlpacaPlugin: Requested market_type '{market_type}' for '{symbol}'. Alpaca plugin primarily handles 'spot' (us_equity). Returning limited info or error.")
             # For non-spot, Alpaca's handling (e.g. crypto via separate API or future products) would differ.
             # This basic plugin focuses on us_equity spot.
             raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, f"market_type '{market_type}' for get_instrument_trading_details")

        asset_info = await self.get_market_info(symbol) # Uses /v2/assets/{symbol}
        if not asset_info:
            logger.warning(f"AlpacaPlugin: No market data found for symbol '{symbol}' on '{self.provider_id}'.")
            raise PluginError(f"Symbol {symbol} not found on {self.provider_id}", self.provider_id)

        # Alpaca precision for stocks is typically high (e.g., notional value, fractional shares)
        # Price precision can vary, but often 2-4 decimal places for display.
        # Amount precision for stocks can be fractional for some, or integer for others.
        # Alpaca API v2 asset details give 'min_trade_increment', 'min_order_size' (notional).
        precision_details: Precision = {
            "amount": int(asset_info.get("min_trade_increment", 1)), # Placeholder, Alpaca allows fractional, but step can be 1 share or 0.00000001 etc.
                                                                  # For fractional, this is complex. If 'easy_to_borrow', likely fractional.
            "price": 2,  # Common for USD denominated stocks, but can vary.
            "cost": 2    # Usually tied to quote currency (USD)
        }
        
        # Limits (these are often per-order and can be complex; Alpaca has notional minimums)
        # e.g. min_order_size: "0.000000001" (notional), "1" (shares)
        # For simplicity, we might not be able to populate all min/max price/amount perfectly from /v2/assets.
        # The `tradable` and `status == active` flags are more critical.
        limits_details: MarketLimits = {
            "amount": None, # Alpaca doesn't have a fixed min/max amount limit for all stocks in /v2/assets
            "cost": {"min": float(asset_info.get("min_order_size", 1.00))} # Notional value, defaults to $1
        }
        if asset_info.get("easy_to_borrow") and asset_info.get("fractionable"):
            # fractional shares have very small min_trade_increment for amount
            if asset_info.get("min_trade_increment"):
                # This value can be like "0.00000001"
                # Determining decimal places from this string is non-trivial if it's not a power of 10
                # For simplicity, if fractional, assume high precision for amount
                precision_details["amount"] = 9 # Alpaca supports up to 9 decimal places for fractional shares.
            else: # if min_trade_increment is not available
                precision_details["amount"] = 2 # fallback to 2 decimal places for non-fractional for safety

        supported_order_types = ['market', 'limit', 'stop', 'stop_limit', 'trailing_stop'] # Common Alpaca types
        if asset_info.get('options_enabled', False): # Example, if Alpaca provided such a flag
            supported_order_types.append('option_specific_type')


        details: InstrumentTradingDetails = {
            "symbol": symbol,
            "market_type": 'spot', # Explicitly spot as this plugin is for us_equity
            "base_currency": symbol, # For stocks, symbol is usually the base
            "quote_currency": "USD", # Assume USD for Alpaca US equity
            "is_active": asset_info.get('status') == 'active' and asset_info.get('tradable', False),
            "precision": precision_details,
            "limits": limits_details,
            "supported_order_types": supported_order_types,
            "default_order_type": "limit",
            "time_in_force_options": ["day", "gtc", "opg", "cls", "ioc", "fok"], # Standard Alpaca TIFs
            "margin_details": { # Alpaca allows margin trading on many stocks
                "is_available": asset_info.get('marginable', False),
                "modes_available": None, # Alpaca doesn't have distinct cross/isolated modes per order in the same way as crypto futures
                "max_leverage": 4.0 if asset_info.get('marginable') else 1.0 # Example: 4x day trading, 2x overnight for Reg T
            },
            "raw_exchange_info": asset_info
        }
        logger.info(f"AlpacaPlugin: Prepared instrument trading details for {log_context}")
        return details

    async def place_order(
        self, symbol: str, order_type: str, side: str, amount: float,
        price: Optional[float] = None, params: Optional[Dict[str, Any]] = None
    ) -> Order:
        logger.warning(f"Trading method 'place_order' not yet fully implemented for AlpacaPlugin. Provider: {self.provider_id}")
        raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "place_order")

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.warning(f"Trading method 'cancel_order' not yet fully implemented for AlpacaPlugin. Provider: {self.provider_id}")
        raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "cancel_order")

    async def get_order_status(self, order_id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Order:
        logger.warning(f"Trading method 'get_order_status' not yet fully implemented for AlpacaPlugin. Provider: {self.provider_id}")
        raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "get_order_status")

    async def get_account_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Balance]:
        logger.warning(f"Trading method 'get_account_balance' not yet fully implemented for AlpacaPlugin. Provider: {self.provider_id}")
        raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "get_account_balance")

    async def get_open_positions(self, symbols: Optional[List[str]] = None, params: Optional[Dict[str, Any]] = None) -> List[Position]:
        logger.warning(f"Trading method 'get_open_positions' not yet fully implemented for AlpacaPlugin. Provider: {self.provider_id}")
        raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, "get_open_positions")
    
    async def get_supported_features(self) -> Dict[str, bool]:
        # Base features from MarketPlugin, override as needed
        base_features = await super().get_supported_features() 
        base_features.update({
            "get_market_info": True, # Implemented
            "validate_symbol": True, # Implemented
            "get_supported_timeframes": True, # Implemented with hardcoded values
            "get_fetch_ohlcv_limit": True,    # Implemented with hardcoded value
            "fetch_instrument_trading_details": True, # Now implemented
            "trading_api": False, # Set to True once trading methods are fully implemented
        })
        return base_features

    async def close(self) -> None:
        # ... (your existing close implementation) ...
        logger.info(f"AlpacaPlugin '{self.provider_id}': Closing instance resources (specialized for us_equity).")
        async with self._session_lock:
            sessions = [self._session_data, self._session_trading]
            for i, session in enumerate(sessions):
                if session and not session.closed:
                    try: await session.close()
                    except Exception as e: logger.error(f"AlpacaPlugin error closing session {i}: {e}", exc_info=True)
            self._session_data, self._session_trading = None, None
        self._validate_symbol_cache.clear()
        self._market_info_cache.clear()
        self._assets_cache = (None, 0.0) 
        self._supported_timeframes_cache = None
        self._fetch_limit_cache = None
        logger.info(f"AlpacaPlugin '{self.provider_id}': Sessions closed and caches cleared.")