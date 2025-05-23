# plugins/alpaca.py

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp # For making HTTP requests to Alpaca API

from plugins.base import (
    MarketPlugin,
    PluginError,
    AuthenticationPluginError,
    NetworkPluginError,
    PluginFeatureNotSupportedError,
    OHLCVBar  # TypedDict for OHLCV data
)
# Removed: from utils.timeframes import normalize_timeframe_ccxt
# AlpacaPlugin will map from a standard internal timeframe.

logger = logging.getLogger(__name__)

# Alpaca API base URLs (Consider moving to a config or constants file if shared/more complex)
ALPACA_BASE_URL_PAPER = "https://paper-api.alpaca.markets"
ALPACA_BASE_URL_LIVE = "https://api.alpaca.markets"
ALPACA_DATA_URL = "https://data.alpaca.markets" # v2 data API for bars

class AlpacaPlugin(MarketPlugin):
    """
    MarketPlugin implementation for Alpaca.

    This plugin class is identified by `plugin_key = "alpaca"` and handles markets
    like "stocks" or "us_equity", specifically for the "alpaca" provider.
    It connects to Alpaca's API (Data API v2 for market data, Trading API v2 for account/asset info)
    to fetch market data. It is configured by MarketService for a specific Alpaca account
    (via API keys) and environment (live or paper/testnet).
    """
    plugin_key: str = "alpaca"
    supported_markets: List[str] = ["stocks", "us_equity"] # Markets this plugin class can handle

    # --- Initialization and Class Methods ---
    def __init__(
        self,
        provider_id: str, # Expected to be "alpaca", enforced below
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None, # Not used by Alpaca REST, but part of base signature
        is_testnet: bool = False, # True for paper trading
        request_timeout: int = 30000,
        verbose_logging: bool = False,
        **kwargs: Any
    ):
        """
        Initializes the AlpacaPlugin instance.

        Args:
            provider_id (str): Must be "alpaca" for this plugin.
            api_key (Optional[str]): Alpaca API Key ID. Falls back to ALPACA_API_KEY env var if None.
            api_secret (Optional[str]): Alpaca API Secret Key. Falls back to ALPACA_API_SECRET env var if None.
            api_passphrase (Optional[str]): Not used by Alpaca REST APIs.
            is_testnet (bool): True for paper trading (uses paper trading URLs), False for live.
            request_timeout (int): HTTP request timeout in milliseconds.
            verbose_logging (bool): Enables more detailed logging during API requests.
            **kwargs: Catches any other arguments from MarketService.
        """
        if provider_id.lower() != "alpaca":
            raise PluginError(
                message=f"AlpacaPlugin initialized with incorrect provider_id: '{provider_id}'. Expected 'alpaca'.",
                provider_id=provider_id
            )

        # Call super() with the standardized provider_id for this plugin instance
        super().__init__(
            provider_id="alpaca", # This instance will always handle "alpaca"
            api_key=api_key or os.getenv("ALPACA_API_KEY"), # Prioritize args, then env vars
            api_secret=api_secret or os.getenv("ALPACA_API_SECRET"),
            api_passphrase=api_passphrase, # Will be None, Alpaca doesn't use
            is_testnet=is_testnet,
            request_timeout=request_timeout,
            verbose_logging=verbose_logging,
            **kwargs
        )

        # Alpaca specific attributes
        self._base_url_trading_api = ALPACA_BASE_URL_PAPER if self.is_testnet else ALPACA_BASE_URL_LIVE
        self._base_url_data_api = ALPACA_DATA_URL # Data API is the same for live/paper

        self._session_data: Optional[aiohttp.ClientSession] = None
        self._session_trading: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock() # Lock for initializing sessions

        # Instance-specific caches
        self._validate_symbol_cache: Dict[str, bool] = {}
        self._market_info_cache: Dict[str, Any] = {}
        self._supported_timeframes_cache: Optional[List[str]] = None
        self._fetch_limit_cache: Optional[int] = None

        if not self.api_key or not self.api_secret:
            logger.warning(
                f"AlpacaPlugin for '{self.provider_id}' initialized without API Key ID or Secret Key. "
                "Operations requiring authentication will fail. Ensure ALPACA_API_KEY and "
                "ALPACA_API_SECRET are set in environment or provided if authenticated access is needed."
            )
        logger.info(
            f"AlpacaPlugin instance initialized. Provider: '{self.provider_id}', "
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
        """AlpacaPlugin class handles only the 'alpaca' provider."""
        return ["alpaca"]

    # --- Internal Session and Request Helpers ---

    async def _get_auth_headers(self) -> Dict[str, str]:
        """Ensures API keys are present and returns auth headers."""
        if not self.api_key or not self.api_secret:
            raise AuthenticationPluginError(
                provider_id=self.provider_id,
                message="API Key ID and Secret Key are required for this Alpaca API operation."
            )
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret
        }

    async def _get_data_session(self) -> aiohttp.ClientSession:
        """Ensures an aiohttp session for Alpaca Data API v2 is available and returns it."""
        async with self._session_lock:
            if self._session_data is None or self._session_data.closed:
                headers = await self._get_auth_headers() # Data API requires keys
                timeout_seconds = self.request_timeout / 1000.0
                timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                self._session_data = aiohttp.ClientSession(headers=headers, timeout=timeout)
                logger.debug(f"AlpacaPlugin '{self.provider_id}': New aiohttp.ClientSession (Data API) created.")
            return self._session_data

    async def _get_trading_session(self) -> aiohttp.ClientSession:
        """Ensures an aiohttp session for Alpaca Trading API is available and returns it."""
        async with self._session_lock:
            if self._session_trading is None or self._session_trading.closed:
                headers = await self._get_auth_headers() # Trading API requires keys
                timeout_seconds = self.request_timeout / 1000.0
                timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                self._session_trading = aiohttp.ClientSession(headers=headers, timeout=timeout)
                logger.debug(f"AlpacaPlugin '{self.provider_id}': New aiohttp.ClientSession (Trading API) created.")
            return self._session_trading

    async def _request_api(
        self,
        session_type: str, # "data" or "trading"
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET"
    ) -> Dict[str, Any]:
        """Generic helper to make requests to Alpaca APIs, handling errors and response parsing."""
        session: aiohttp.ClientSession
        base_url: str

        if session_type == "data":
            session = await self._get_data_session()
            base_url = self._base_url_data_api
        elif session_type == "trading":
            session = await self._get_trading_session()
            base_url = self._base_url_trading_api
        else:
            raise ValueError(f"Invalid session_type for _request_api: {session_type}")

        url = f"{base_url}{endpoint}"
        response_text_snippet = "" # For logging

        try:
            if self.verbose_logging:
                logger.debug(f"AlpacaPlugin '{self.provider_id}': Requesting {method} {url}, Params: {params}")

            async with session.request(method, url, params=params) as response:
                response_text = await response.text()
                response_text_snippet = response_text[:500] # Log snippet

                if self.verbose_logging:
                    logger.debug(f"AlpacaPlugin '{self.provider_id}': Response status {response.status} from {url}. Body snippet: {response_text_snippet}")

                if response.status == 401 or response.status == 403:
                    raise AuthenticationPluginError(provider_id=self.provider_id, message=f"API Error {response.status}: {response_text_snippet}")
                if response.status == 429: # Rate limit
                    raise NetworkPluginError(provider_id=self.provider_id, message=f"API Error 429 (Rate Limit Exceeded): {response_text_snippet}")
                if response.status == 404: # Not Found
                     raise PluginError(provider_id=self.provider_id, message=f"API Error 404 (Not Found) for {url}: {response_text_snippet}")

                response.raise_for_status() # Raises HTTPError for other 4XX, 5XX
                
                # Alpaca sometimes returns empty body for success (e.g. 204 No Content for cancel order)
                # For GETs that expect JSON, ensure there's content.
                if response.status == 204: # No content
                    return {} # Return empty dict for 204
                
                data = await response.json(content_type=None) # content_type=None to handle various responses
                return data if isinstance(data, dict) else {} # Ensure dict return for consistency if API gives list for some asset endpoints
        
        except aiohttp.ClientResponseError as e: # Handles errors raised by response.raise_for_status()
            # We've already handled 401, 403, 429, 404 above if they occur before raise_for_status.
            # This will catch other HTTP errors.
            logger.error(f"AlpacaPlugin '{self.provider_id}': HTTP error {e.status} for {url}: {e.message}. Response: {response_text_snippet}", exc_info=False) # No need for full exc_info if snippet is good
            raise PluginError(message=f"HTTP error {e.status}: {e.message}", provider_id=self.provider_id, original_exception=e) from e
        except asyncio.TimeoutError as e_timeout:
            logger.error(f"AlpacaPlugin '{self.provider_id}': Request timeout for {url}: {e_timeout}", exc_info=True)
            raise NetworkPluginError(provider_id=self.provider_id, message="Request timed out", original_exception=e_timeout) from e_timeout
        except aiohttp.ClientError as e_client: # Other client errors (connection, SSL, etc.)
            logger.error(f"AlpacaPlugin '{self.provider_id}': Client error for {url}: {e_client}", exc_info=True)
            raise NetworkPluginError(provider_id=self.provider_id, message=f"Client connection error: {e_client}", original_exception=e_client) from e_client
        except Exception as e_unexpected:
            logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error requesting {url}: {e_unexpected}", exc_info=True)
            raise PluginError(message=f"Unexpected API error: {e_unexpected}", provider_id=self.provider_id, original_exception=e_unexpected) from e_unexpected

    def _map_to_alpaca_timeframe(self, internal_timeframe: str) -> str:
        """
        Maps a standard internal timeframe string (e.g., "1m", "1D") to Alpaca's Data API v2 format.
        Alpaca uses: 1Min, 5Min, 15Min, 30Min, 1H (or 1Hour), 1D (or 1Day).
        Refer to Alpaca documentation for the most current formats.
        """
        mapping = {
            "1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min",
            "1h": "1Hour", "1H": "1Hour", # Accept both "1h" and "1H"
            "1d": "1Day", "1D": "1Day",   # Accept both "1d" and "1D"
            # Alpaca's /bars endpoint does not typically support 1W or 1M directly for raw bars.
            # These are usually for aggregate endpoints or might require different handling.
            # If your app uses "1W", "1M", decide how to handle (e.g., error, or fetch daily and resample higher up).
        }
        # Fallback to a common default if specific mapping not found, or raise error
        # For now, let's try to pass it through and let Alpaca reject if invalid for /bars
        alpaca_tf = mapping.get(internal_timeframe, internal_timeframe)
        if alpaca_tf == internal_timeframe and internal_timeframe not in mapping.values():
             logger.warning(f"AlpacaPlugin '{self.provider_id}': Timeframe '{internal_timeframe}' has no direct Alpaca mapping. Passing as is. This may fail.")
        return alpaca_tf

    # --- MarketPlugin ABC Implementation ---

    async def get_symbols(self) -> List[str]:
        """
        Fetches tradable US equity symbols from Alpaca using the /v2/assets endpoint.
        Requires API keys with trading permissions.
        """
        logger.debug(f"AlpacaPlugin '{self.provider_id}': Fetching symbols (assets).")
        try:
            assets_response_data = await self._request_api(
                session_type="trading",
                endpoint="/v2/assets",
                params={"status": "active", "asset_class": "us_equity", "tradable": "true"} # Common filters
            )
            
            symbols: List[str] = []
            if isinstance(assets_response_data, list): # Alpaca /v2/assets returns a list of asset objects
                for asset in assets_response_data:
                    if isinstance(asset, dict) and asset.get("symbol") and asset.get("tradable"):
                        symbols.append(asset["symbol"])
            else:
                # This case should ideally be caught by _request_api if response is not JSON list.
                logger.warning(f"AlpacaPlugin '{self.provider_id}': Unexpected response format for assets: {type(assets_response_data)}. Expected list.")

            logger.info(f"AlpacaPlugin '{self.provider_id}': Fetched {len(symbols)} active, tradable US equity symbols.")
            return sorted(symbols)
        except AuthenticationPluginError: # Re-raise if _request_api determined it
            raise
        except PluginError as e: # Catch other plugin errors from _request_api
            logger.error(f"AlpacaPlugin '{self.provider_id}': PluginError fetching symbols: {e}", exc_info=False)
            raise
        except Exception as e: # Catch any other unexpected error
            logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error fetching symbols: {e}", exc_info=True)
            raise PluginError(message=f"Unexpected error fetching symbols: {e}", provider_id=self.provider_id, original_exception=e) from e

    async def fetch_historical_ohlcv(
        self, symbol: str, timeframe: str,
        since: Optional[int] = None, limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> List[OHLCVBar]:
        """
        Fetches historical OHLCV data for US equities from Alpaca Data API v2 (/v2/stocks/{symbol}/bars).
        """
        alpaca_tf = self._map_to_alpaca_timeframe(timeframe)
        
        api_params: Dict[str, Any] = {"timeframe": alpaca_tf, "adjustment": "raw"}
        if limit is not None:
            # Alpaca's /bars endpoint has a max limit, typically 10,000 for stocks.
            # This plugin's get_fetch_ohlcv_limit() should provide this.
            max_limit_plugin = await self.get_fetch_ohlcv_limit()
            api_params["limit"] = min(limit, max_limit_plugin)
        else:
            # It's good to have a default if caller doesn't specify.
            # MarketService/DataOrchestrator often sets this.
            api_params["limit"] = await self.get_fetch_ohlcv_limit() 

        if since is not None:
            # Alpaca expects ISO 8601 format for start/end times
            api_params["start"] = datetime.fromtimestamp(since / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        
        # Handle 'until' if passed in params (e.g., as 'until_ms')
        # Alpaca uses 'end' for the 'until' parameter.
        if params and params.get("until_ms"):
            until_ms = params["until_ms"]
            api_params["end"] = datetime.fromtimestamp(until_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        elif params and params.get("end"): # If 'end' is already in ISO format
            api_params["end"] = params["end"]


        # Endpoint for stock bars
        endpoint = f"/v2/stocks/{symbol}/bars"
        
        logger.debug(f"AlpacaPlugin '{self.provider_id}': Fetching historical OHLCV for {symbol} @ {alpaca_tf}. API Params: {api_params}")

        try:
            response_data = await self._request_api("data", endpoint, params=api_params)
            
            parsed_bars: List[OHLCVBar] = []
            # Alpaca response structure: {"bars": [{"t": "...", "o": ..., ...}, ...], "symbol": "...", "next_page_token": null}
            if response_data and "bars" in response_data and isinstance(response_data["bars"], list):
                for bar_data in response_data["bars"]:
                    try:
                        ts_str = bar_data.get("t")
                        if not ts_str: continue # Skip bar if timestamp is missing

                        # Alpaca timestamps are typically RFC3339 format e.g., "2021-01-01T05:00:00Z"
                        dt_obj = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        timestamp_ms = int(dt_obj.timestamp() * 1000)

                        parsed_bars.append({
                            "timestamp": timestamp_ms,
                            "open": float(bar_data["o"]), "high": float(bar_data["h"]),
                            "low": float(bar_data["l"]), "close": float(bar_data["c"]),
                            "volume": float(bar_data["v"]),
                        })
                    except (KeyError, TypeError, ValueError) as e_parse:
                        logger.warning(f"AlpacaPlugin '{self.provider_id}': Error parsing bar for {symbol}: {bar_data}. Error: {e_parse}. Skipping bar.", exc_info=False)
                        continue
            
            logger.info(f"AlpacaPlugin '{self.provider_id}': Fetched {len(parsed_bars)} OHLCV bars for {symbol}/{timeframe} (Alpaca TF: {alpaca_tf}).")
            # Alpaca returns bars sorted oldest to newest if 'start' is provided.
            # If only 'end' and 'limit' are used, it's newest to oldest.
            # This implementation implicitly fetches oldest to newest if 'since' is used.
            # If 'since' is not used, Alpaca defaults to recent data.
            # The caller (DataOrchestrator) might re-sort if needed or rely on this order.
            return parsed_bars
        except PluginError: # Re-raise specific plugin errors from _request_api
            raise
        except Exception as e: # Catch any other unexpected error
            logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error in fetch_historical_ohlcv for {symbol}: {e}", exc_info=True)
            raise PluginError(message=f"Unexpected error fetching OHLCV: {e}", provider_id=self.provider_id, original_exception=e) from e

    async def fetch_latest_ohlcv(self, symbol: str, timeframe: str = "1m") -> Optional[OHLCVBar]:
        """
        Fetches the most recent OHLCV bar for a stock symbol from Alpaca.
        Uses /v2/stocks/{symbol}/bars/latest if timeframe is 1Min or 1Day,
        otherwise uses fetch_historical_ohlcv with limit=1.
        """
        logger.debug(f"AlpacaPlugin '{self.provider_id}': Fetching latest '{timeframe}' bar for {symbol}.")
        alpaca_tf_for_latest = self._map_to_alpaca_timeframe(timeframe) # Map to Alpaca's like "1Min", "1Day"

        # Alpaca has a specific endpoint for "latest" bar data for stocks.
        # GET /v2/stocks/{symbol}/bars/latest - only supports timeframe 1Min, 1Day
        if alpaca_tf_for_latest in ["1Min", "1Day"]:
            endpoint = f"/v2/stocks/{symbol}/bars/latest"
            api_params = {"timeframe": alpaca_tf_for_latest}
            logger.debug(f"AlpacaPlugin '{self.provider_id}': Using latest bar endpoint: {endpoint} with params: {api_params}")
            try:
                response_data = await self._request_api("data", endpoint, params=api_params)
                # Expected response: {"bar": {"t":..., "o":..., ...}, "symbol":"..."}
                if response_data and "bar" in response_data and isinstance(response_data["bar"], dict):
                    bar_data = response_data["bar"]
                    ts_str = bar_data.get("t")
                    if not ts_str: return None

                    dt_obj = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    timestamp_ms = int(dt_obj.timestamp() * 1000)
                    latest_bar: OHLCVBar = {
                        "timestamp": timestamp_ms,
                        "open": float(bar_data["o"]), "high": float(bar_data["h"]),
                        "low": float(bar_data["l"]), "close": float(bar_data["c"]),
                        "volume": float(bar_data["v"]),
                    }
                    logger.info(f"AlpacaPlugin '{self.provider_id}': Successfully fetched latest '{timeframe}' bar for {symbol} via latest endpoint @ {datetime.fromtimestamp(latest_bar['timestamp']/1000, tz=timezone.utc).isoformat()}")
                    return latest_bar
                logger.warning(f"AlpacaPlugin '{self.provider_id}': No latest bar data in response for {symbol} from /latest endpoint.")
                return None
            except PluginError as e:
                # If /latest fails (e.g. 404 if symbol has no recent 1Min/1Day bar), fallback or log
                logger.warning(f"AlpacaPlugin '{self.provider_id}': PluginError fetching latest bar for {symbol}/{timeframe} via /latest: {e}. Will attempt fallback.")
                # Fall through to historical fetch if /latest doesn't work or for other timeframes
            except Exception as e:
                logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error fetching latest bar for {symbol}/{timeframe} via /latest: {e}", exc_info=True)
                # Fall through
        
        # Fallback or for other timeframes: use historical fetch with limit=1 (or small limit)
        logger.debug(f"AlpacaPlugin '{self.provider_id}': Using historical fetch as fallback/default for latest '{timeframe}' bar for {symbol}.")
        try:
            # Fetch a few recent bars to increase chance of getting the latest *complete* one.
            lookback_periods = 2
            # Estimate a 'since' time to ensure the latest bar is captured.
            # This is a rough estimation.
            now_dt = datetime.now(timezone.utc)
            since_dt_approx = now_dt - timedelta(days=2) # Go back 2 days as a safe bet for any timeframe.
            # More precise would be to parse 'timeframe' and calculate period_ms * lookback_periods.
            # For simplicity here, a fixed lookback window.
            since_ms_approx = int(since_dt_approx.timestamp() * 1000)

            bars = await self.fetch_historical_ohlcv(
                symbol=symbol, 
                timeframe=timeframe, # Use the original requested timeframe here for mapping.
                since=since_ms_approx, 
                limit=lookback_periods 
            )
            if bars:
                latest_bar = bars[-1] # The last bar in the list (sorted by time) is the most recent.
                logger.info(f"AlpacaPlugin '{self.provider_id}': Fetched latest '{timeframe}' bar for {symbol} via historical (fallback) @ {datetime.fromtimestamp(latest_bar['timestamp']/1000, tz=timezone.utc).isoformat()}")
                return latest_bar
            
            logger.warning(f"AlpacaPlugin '{self.provider_id}': No latest '{timeframe}' bar returned for {symbol} via historical fetch.")
            return None
        except PluginError as e: # Catch errors from the historical fetch
            logger.error(f"AlpacaPlugin '{self.provider_id}': PluginError during fallback latest bar fetch for {symbol}/{timeframe}: {e}", exc_info=False)
            return None
        except Exception as e: # Catch any other unexpected error
            logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error during fallback latest bar fetch for {symbol}/{timeframe}: {e}", exc_info=True)
            return None

    # --- Optional Utility / Metadata Methods ---

    async def get_market_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetches asset details for a specific symbol from Alpaca using /v2/assets/{symbol}."""
        if symbol in self._market_info_cache:
             return self._market_info_cache[symbol].get('data')


        logger.debug(f"AlpacaPlugin '{self.provider_id}': Fetching market info (asset details) for '{symbol}'.")
        try:
            asset_data = await self._request_api(
                session_type="trading",
                endpoint=f"/v2/assets/{symbol}"
            )
            if asset_data and isinstance(asset_data, dict):
                 # Example of extracting some useful fields, can be expanded.
                info_to_cache = {
                    "id": asset_data.get("id"),
                    "symbol": asset_data.get("symbol"),
                    "name": asset_data.get("name"),
                    "exchange": asset_data.get("exchange"),
                    "asset_class": asset_data.get("asset_class"),
                    "status": asset_data.get("status"), # 'active', 'inactive'
                    "tradable": asset_data.get("tradable"),
                    "marginable": asset_data.get("marginable"),
                    "shortable": asset_data.get("shortable"),
                    "easy_to_borrow": asset_data.get("easy_to_borrow"),
                    "fractionable": asset_data.get("fractionable"),
                    # Add more fields as needed from Alpaca's asset object
                }
                self._market_info_cache[symbol] = {'data': info_to_cache, 'timestamp': time.monotonic()}
                logger.info(f"AlpacaPlugin '{self.provider_id}': Fetched and cached market info for '{symbol}'.")
                return info_to_cache
            
            logger.warning(f"AlpacaPlugin '{self.provider_id}': No market info returned or unexpected format for '{symbol}'. Response: {asset_data}")
            self._market_info_cache[symbol] = {'data': None, 'timestamp': time.monotonic()} # Cache miss
            return None
        except PluginError as e:
            if "404 (Not Found)" in str(e):
                logger.info(f"AlpacaPlugin '{self.provider_id}': Market info not found for symbol '{symbol}' (likely does not exist).")
                self._market_info_cache[symbol] = {'data': None, 'timestamp': time.monotonic()}
                return None
            logger.error(f"AlpacaPlugin '{self.provider_id}': PluginError fetching market info for '{symbol}': {e}", exc_info=False)
            raise # Re-raise other plugin errors
        except Exception as e: # Catch any other unexpected error
            logger.error(f"AlpacaPlugin '{self.provider_id}': Unexpected error fetching market info for '{symbol}': {e}", exc_info=True)
            raise PluginError(message=f"Unexpected error fetching market info for {symbol}: {e}", provider_id=self.provider_id, original_exception=e) from e

    async def validate_symbol(self, symbol: str) -> bool:
        """Validates if a symbol exists and is tradable via Alpaca by fetching its asset details."""
        if symbol in self._validate_symbol_cache: # Check instance cache first
            return self._validate_symbol_cache[symbol]

        logger.debug(f"AlpacaPlugin '{self.provider_id}': Validating symbol '{symbol}'.")
        try:
            asset_info = await self.get_market_info(symbol)
            is_valid = asset_info is not None and \
                       asset_info.get('tradable', False) and \
                       asset_info.get('status') == 'active'
            
            if asset_info and not is_valid:
                logger.info(f"AlpacaPlugin '{self.provider_id}': Symbol '{symbol}' found but is not active and tradable. Tradable: {asset_info.get('tradable')}, Status: {asset_info.get('status')}.")

            self._validate_symbol_cache[symbol] = is_valid
            return is_valid
        except AuthenticationPluginError:
             logger.warning(f"AlpacaPlugin '{self.provider_id}': Cannot validate symbol '{symbol}' without API keys (get_market_info requires auth).")
             return False # Cannot validate without auth
        except PluginError: # Handles "not found" from get_market_info or other plugin errors during fetch
            self._validate_symbol_cache[symbol] = False
            return False
        except Exception: 
            logger.exception(f"AlpacaPlugin '{self.provider_id}': Unexpected error during validate_symbol for '{symbol}'. Assuming invalid.")
            self._validate_symbol_cache[symbol] = False
            return False

    async def get_supported_timeframes(self) -> Optional[List[str]]:
        """
        Returns timeframes natively supported by Alpaca Data API v2 for the `/bars` endpoint.
        These are the internal standard timeframes that can be mapped.
        """
        # These are the internal representations that _map_to_alpaca_timeframe can handle
        # for the /v2/stocks/{symbol}/bars endpoint.
        if self._supported_timeframes_cache is None:
            self._supported_timeframes_cache = ["1m", "5m", "15m", "30m", "1h", "1H", "1d", "1D"]
        return self._supported_timeframes_cache

    async def get_fetch_ohlcv_limit(self) -> int:
        """Alpaca Data API v2 /bars endpoint limit for stocks."""
        # As per Alpaca documentation (may change, but often around 1000 or 10000 for stocks).
        # For /v2/stocks/{symbol}/bars, it's often 10,000.
        if self._fetch_limit_cache is None:
            self._fetch_limit_cache = 10000
        return self._fetch_limit_cache
        
    async def get_supported_features(self) -> Dict[str, bool]:
        """Declare supported features for Alpaca market data plugin."""
        return {
            "watch_ticks": False,  # Alpaca has streaming, but this plugin doesn't implement WebSocket ticks
            "fetch_trades": False, # Alpaca has trades data, but not implemented here
            "trading_api": False,  # This plugin instance is for market data; trading is separate
            "get_market_info": True,
            "validate_symbol": True,
            "get_supported_timeframes": True,
            "get_fetch_ohlcv_limit": True,
        }

    async def close(self) -> None:
        """Closes the aiohttp ClientSessions if they were created and clears instance caches."""
        logger.info(f"AlpacaPlugin '{self.provider_id}': Closing instance resources.")
        async with self._session_lock:
            sessions_to_close: List[Optional[aiohttp.ClientSession]] = [self._session_data, self._session_trading]
            for i, session in enumerate(sessions_to_close):
                session_name = "Data API" if i == 0 else "Trading API"
                if session and not session.closed:
                    try:
                        await session.close()
                        logger.debug(f"AlpacaPlugin '{self.provider_id}': aiohttp.ClientSession ({session_name}) closed.")
                    except Exception as e_close:
                        logger.error(f"AlpacaPlugin '{self.provider_id}': Error closing ClientSession ({session_name}): {e_close}", exc_info=True)
            self._session_data = None
            self._session_trading = None
        
        self._validate_symbol_cache.clear()
        self._market_info_cache.clear()
        self._supported_timeframes_cache = None
        self._fetch_limit_cache = None
        logger.info(f"AlpacaPlugin '{self.provider_id}': Instance sessions closed and caches cleared.")