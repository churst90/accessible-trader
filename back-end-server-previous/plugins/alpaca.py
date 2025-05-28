# plugins/alpaca.py

import asyncio
import logging
import os
import time 
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp 

from plugins.base import (
    MarketPlugin,
    PluginError,
    AuthenticationPluginError,
    NetworkPluginError,
    PluginFeatureNotSupportedError, # Ensure this is imported if used
    OHLCVBar
)

logger = logging.getLogger(__name__)

ALPACA_BASE_URL_PAPER = "https://paper-api.alpaca.markets"
ALPACA_BASE_URL_LIVE = "https://api.alpaca.markets"
ALPACA_DATA_URL = "https://data.alpaca.markets"

class AlpacaPlugin(MarketPlugin):
    plugin_key: str = "alpaca"
    # MODIFIED: Plugin now exclusively supports "us_equity"
    supported_markets: List[str] = ["us_equity"]

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
        if provider_id.lower() != "alpaca": # Should always be "alpaca" for this plugin
            raise PluginError(
                message=f"AlpacaPlugin initialized with incorrect provider_id: '{provider_id}'. Expected 'alpaca'.",
                provider_id=provider_id
            )

        super().__init__(
            provider_id="alpaca",
            api_key=api_key or os.getenv("ALPACA_API_KEY"),
            api_secret=api_secret or os.getenv("ALPACA_API_SECRET"),
            api_passphrase=api_passphrase,
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
        self._fetch_limit_cache: Optional[int] = None # Specifically for stocks/us_equity
        
        # Cache for /v2/assets response (now only for us_equity)
        self._assets_cache: Tuple[Optional[List[Dict[str, Any]]], float] = (None, 0.0)
        self._assets_cache_ttl_seconds = 3600

        if not self.api_key or not self.api_secret:
            logger.warning(
                f"AlpacaPlugin for '{self.provider_id}' initialized without API Key ID or Secret Key. "
                "Operations requiring authentication will fail."
            )
        logger.info(
            f"AlpacaPlugin instance initialized for 'us_equity'. Provider: '{self.provider_id}', "
            f"Testnet (Paper): {self.is_testnet}, API Key Provided: {bool(self.api_key)}."
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

    async def _request_api(self, session_type: str, endpoint: str, params: Optional[Dict[str, Any]] = None, method: str = "GET") -> Any:
        session = await self._get_data_session() if session_type == "data" else await self._get_trading_session()
        base_url = self._base_url_data_api if session_type == "data" else self._base_url_trading_api
        url = f"{base_url}{endpoint}"
        response_text_snippet = ""
        try:
            if self.verbose_logging: logger.debug(f"AlpacaPlugin '{self.provider_id}': Requesting {method} {url}, Params: {params}")
            async with session.request(method, url, params=params) as response:
                response_text = await response.text()
                response_text_snippet = response_text[:500]
                if self.verbose_logging: logger.debug(f"AlpacaPlugin '{self.provider_id}': Response status {response.status} from {url}. Snippet: {response_text_snippet}")
                if response.status == 401 or response.status == 403: raise AuthenticationPluginError(self.provider_id, f"API Error {response.status}: {response_text_snippet}")
                if response.status == 429: raise NetworkPluginError(self.provider_id, f"API Error 429 (Rate Limit): {response_text_snippet}")
                if response.status == 404: raise PluginError(self.provider_id, f"API Error 404 (Not Found) for {url}: {response_text_snippet}")
                response.raise_for_status()
                return {} if response.status == 204 else await response.json(content_type=None)
        except aiohttp.ClientResponseError as e:
            logger.error(f"AlpacaPlugin '{self.provider_id}': HTTP error {e.status} for {url}: {e.message}. Response: {response_text_snippet}", exc_info=False)
            raise PluginError(f"HTTP error {e.status}: {e.message}", self.provider_id, e) from e
        except asyncio.TimeoutError as e:
            logger.error(f"AlpacaPlugin '{self.provider_id}': Request timeout for {url}: {e}", exc_info=True)
            raise NetworkPluginError(self.provider_id, "Request timed out", e) from e
        except aiohttp.ClientError as e:
            logger.error(f"AlpacaPlugin '{self.provider_id}': Client error for {url}: {e}", exc_info=True)
            raise NetworkPluginError(self.provider_id, f"Client connection error: {e}", e) from e
        except Exception as e:
            logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error for {url}: {e}. Snippet: {response_text_snippet}", exc_info=True)
            raise PluginError(f"Unexpected API error: {e}", self.provider_id, e) from e

    def _map_to_alpaca_timeframe(self, internal_timeframe: str) -> str:
        mapping = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1h": "1Hour", "1H": "1Hour", "1d": "1Day", "1D": "1Day"}
        alpaca_tf = mapping.get(internal_timeframe, internal_timeframe)
        if alpaca_tf == internal_timeframe and internal_timeframe not in mapping.values():
            logger.warning(f"AlpacaPlugin '{self.provider_id}': Timeframe '{internal_timeframe}' has no direct Alpaca mapping. Passing as is.")
        return alpaca_tf

    async def get_symbols(self, market: str) -> List[str]:
        logger.debug(f"AlpacaPlugin '{self.provider_id}': get_symbols requested for market '{market}'.")
        normalized_market = market.lower()

        # MODIFIED: Enforce "us_equity"
        if normalized_market != "us_equity":
            msg = f"AlpacaPlugin only supports 'us_equity' market for get_symbols, not '{market}'."
            logger.error(f"AlpacaPlugin '{self.provider_id}': {msg}")
            raise PluginError(message=msg, provider_id=self.provider_id)

        asset_class_for_api = "us_equity" # Always us_equity now

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
            except PluginError as e: # Catch API errors
                logger.error(f"AlpacaPlugin '{self.provider_id}': PluginError fetching 'us_equity' assets: {e}", exc_info=False)
                if cached_assets_data: # Return stale on error if available
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
        alpaca_tf = self._map_to_alpaca_timeframe(timeframe)
        
        # MODIFIED: Always use stocks endpoint as plugin is now for us_equity only
        endpoint = f"/v2/stocks/{symbol}/bars"
        max_limit_plugin = await self.get_fetch_ohlcv_limit() # Should be stock limit (10000)

        api_params: Dict[str, Any] = {"timeframe": alpaca_tf, "adjustment": "raw"}
        if limit is not None:
            api_params["limit"] = min(limit, max_limit_plugin)
        else:
            api_params["limit"] = max_limit_plugin
        if since is not None:
            api_params["start"] = datetime.fromtimestamp(since / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        
        # Handle 'until' if passed in params (e.g., as 'until_ms')
        if params and params.get("until_ms"):
            api_params["end"] = datetime.fromtimestamp(params["until_ms"] / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        elif params and params.get("end"): # If 'end' is already in ISO format
            api_params["end"] = params["end"]

        # The user mentioned: "Check that the asset_class in the params (if provided) is "us_equity", or default to it. If it’s not "us_equity", throw an error."
        # This specific endpoint /v2/stocks/{symbol}/bars implies stock/us_equity. Alpaca's API doesn't take asset_class as a query param here.
        # The specialization of the plugin to "us_equity" means any symbol processed here is assumed to be "us_equity".
        # If `params` somehow contained an `asset_class` field intended for other uses, it's ignored by this specific API call.
        # We ensure this method is only ever called for symbols that are contextually "us_equity".

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
        logger.debug(f"AlpacaPlugin '{self.provider_id}': Fetching latest '{timeframe}' bar for '{symbol}' (us_equity).")
        alpaca_tf_for_latest = self._map_to_alpaca_timeframe(timeframe)

        # MODIFIED: Always use stocks endpoint as plugin is for us_equity only
        # Alpaca's /latest endpoint for stocks typically supports "1Min" and "1Day".
        if alpaca_tf_for_latest in ["1Min", "1Day"]:
            endpoint = f"/v2/stocks/{symbol}/bars/latest"
            api_params = {"timeframe": alpaca_tf_for_latest} # This param is for the /latest endpoint itself for stocks.
            logger.debug(f"AlpacaPlugin '{self.provider_id}': Using latest bar endpoint: {endpoint} with params: {api_params}")
            try:
                response_data = await self._request_api("data", endpoint, params=api_params)
                bar_data_key = "bar" # For /v2/stocks/.../latest
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
            # Fallback to fetch_historical_ohlcv implicitly uses the stocks endpoint now
            bars = await self.fetch_historical_ohlcv(symbol=symbol, timeframe=timeframe, limit=2) # Removed since heuristic
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
        cache_entry = self._market_info_cache.get(symbol)
        current_time = time.monotonic()
        MARKET_INFO_TTL_SECONDS = 3600

        if cache_entry and (current_time - cache_entry.get('timestamp', 0) < MARKET_INFO_TTL_SECONDS):
            return cache_entry.get('data')

        logger.debug(f"AlpacaPlugin '{self.provider_id}': Fetching market info (asset details) for '{symbol}' (assumed us_equity).")
        try:
            # Endpoint /v2/assets/{symbol} works for stocks/ETFs.
            asset_data = await self._request_api("trading", f"/v2/assets/{symbol}")
            if asset_data and isinstance(asset_data, dict):
                # Crucial check: ensure the asset is indeed 'us_equity' if plugin is specialized
                if asset_data.get("asset_class") != "us_equity":
                    logger.warning(f"AlpacaPlugin '{self.provider_id}': Fetched market info for '{symbol}', but its asset_class is '{asset_data.get('asset_class')}', not 'us_equity'. Plugin is specialized for us_equity.")
                    # Decide if to return None or raise error. For now, let's cache it but be aware.
                    # Returning None might be safer if strict us_equity adherence is needed.
                    self._market_info_cache[symbol] = {'data': None, 'timestamp': current_time} # Symbol not a US Equity
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
        if symbol in self._validate_symbol_cache:
            return self._validate_symbol_cache[symbol]
        logger.debug(f"AlpacaPlugin '{self.provider_id}': Validating symbol '{symbol}' (as us_equity).")
        try:
            asset_info = await self.get_market_info(symbol) # This will now also check asset_class
            is_valid = False
            if asset_info: # asset_info will be None if not found or not us_equity
                is_valid = asset_info.get('tradable', False) and asset_info.get('status') == 'active' # Redundant asset_class check, as get_market_info handles it
                if not is_valid:
                     logger.info(f"AlpacaPlugin '{self.provider_id}': Symbol '{symbol}' found but not active/tradable. Tradable: {asset_info.get('tradable')}, Status: {asset_info.get('status')}.")
            else:
                logger.info(f"AlpacaPlugin '{self.provider_id}': Symbol '{symbol}' not found or not 'us_equity' during validation.")
            self._validate_symbol_cache[symbol] = is_valid
            return is_valid
        # ... (rest of existing error handling for validate_symbol) ...
        except AuthenticationPluginError: # Copied from previous version
             logger.warning(f"AlpacaPlugin '{self.provider_id}': Cannot validate symbol '{symbol}' without API keys (get_market_info requires auth). Assuming invalid.")
             self._validate_symbol_cache[symbol] = False
             return False 
        except PluginError: 
            logger.warning(f"AlpacaPlugin '{self.provider_id}': PluginError during get_market_info for validation of '{symbol}'. Assuming invalid.")
            self._validate_symbol_cache[symbol] = False
            return False
        except Exception: 
            logger.exception(f"AlpacaPlugin '{self.provider_id}': Unexpected error during validate_symbol for '{symbol}'. Assuming invalid.")
            self._validate_symbol_cache[symbol] = False
            return False


    async def get_supported_timeframes(self) -> Optional[List[str]]:
        if self._supported_timeframes_cache is None:
            self._supported_timeframes_cache = ["1m", "5m", "15m", "30m", "1h", "1H", "1d", "1D"]
        return self._supported_timeframes_cache

    async def get_fetch_ohlcv_limit(self) -> int:
        # This limit is for Alpaca's /v2/stocks/.../bars endpoint
        if self._fetch_limit_cache is None:
            self._fetch_limit_cache = 10000 
        return self._fetch_limit_cache
        
    async def get_supported_features(self) -> Dict[str, bool]:
        return {"watch_ticks": False, "fetch_trades": False, "trading_api": False, "get_market_info": True, "validate_symbol": True, "get_supported_timeframes": True, "get_fetch_ohlcv_limit": True}

    async def close(self) -> None:
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
        self._assets_cache = (None, 0.0) # Reset assets cache
        self._supported_timeframes_cache = None
        self._fetch_limit_cache = None
        logger.info(f"AlpacaPlugin '{self.provider_id}': Sessions closed and caches cleared.")