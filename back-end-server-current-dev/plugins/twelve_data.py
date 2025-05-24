# plugins/twelve_data.py

import asyncio
import logging
import os
import time
import random # For retry jitter
from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from plugins.base import (
    MarketPlugin,
    PluginError,
    AuthenticationPluginError,
    NetworkPluginError,
    PluginFeatureNotSupportedError,
    OHLCVBar
)
from utils.timeframes import format_timestamp_to_iso # For logging

logger = logging.getLogger(__name__)

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"

# Default retry configuration
DEFAULT_TWELVE_RETRY_COUNT = 3
DEFAULT_TWELVE_RETRY_DELAY_BASE_S = 1.5 # Twelve Data can be sensitive to rapid retries

# Cache TTLs (in seconds)
SYMBOLS_CACHE_TTL_SECONDS = 6 * 3600  # 6 hours
MARKET_INFO_CACHE_TTL_SECONDS = 24 * 3600 # 24 hours

class TwelveDataPlugin(MarketPlugin):
    plugin_key: str = "twelve_data"
    # Based on Twelve Data's typical offerings.
    supported_markets: List[str] = ["us_equity", "global_equity", "forex", "crypto", "indices", "etf"]

    def __init__(
        self,
        provider_id: str, # Expected to be "twelvedata"
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None, # Not used by Twelve Data
        api_passphrase: Optional[str] = None, # Not used by Twelve Data
        is_testnet: bool = False, # Twelve Data doesn't have a distinct testnet mode via URL
        request_timeout: int = 30000,
        verbose_logging: bool = False,
        retry_count: int = DEFAULT_TWELVE_RETRY_COUNT,
        retry_delay_base: float = DEFAULT_TWELVE_RETRY_DELAY_BASE_S,
        **kwargs: Any
    ):
        if provider_id.lower() != "twelvedata":
            raise PluginError(
                message=f"TwelveDataPlugin initialized with incorrect provider_id: '{provider_id}'. Expected 'twelvedata'.",
                provider_id=provider_id
            )

        resolved_api_key = api_key or os.getenv("TWELVE_DATA_API_KEY")

        super().__init__(
            provider_id="twelvedata",
            api_key=resolved_api_key,
            api_secret=None,
            api_passphrase=None,
            is_testnet=is_testnet,
            request_timeout=request_timeout,
            verbose_logging=verbose_logging,
            **kwargs
        )

        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        
        self.retry_count = retry_count
        self.retry_delay_base = retry_delay_base

        self._symbols_cache: Dict[str, Tuple[Optional[List[str]], float]] = {}
        self._market_info_cache: Dict[str, Tuple[Optional[Dict[str, Any]], float]] = {}
        self._supported_timeframes_cache: Optional[List[str]] = None
        # Twelve Data limit: max 5000 per request for time_series
        self._fetch_limit_cache: Optional[int] = 5000 

        if not self.api_key:
            logger.warning(
                f"TwelveDataPlugin for '{self.provider_id}' initialized without an API Key. "
                "Operations will fail or use a very limited free tier. "
                "Ensure TWELVE_DATA_API_KEY is set in environment or provided."
            )
        logger.info(
            f"TwelveDataPlugin instance initialized. Provider: '{self.provider_id}', API Key Provided: {bool(self.api_key)}."
        )

    @classmethod
    def get_plugin_key(cls) -> str:
        return cls.plugin_key

    @classmethod
    def get_supported_markets(cls) -> List[str]:
        return cls.supported_markets

    @classmethod
    def list_configurable_providers(cls) -> List[str]:
        return ["twelvedata"]

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session is None or self._session.closed:
                timeout_seconds = self.request_timeout / 1000.0
                timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                self._session = aiohttp.ClientSession(timeout=timeout)
                logger.debug(f"TwelveDataPlugin '{self.provider_id}': New aiohttp.ClientSession created.")
            return self._session

    async def _request_api(
        self,
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET"
    ) -> Any:
        if not self.api_key:
            raise AuthenticationPluginError(
                provider_id=self.provider_id,
                message="Twelve Data API Key is required."
            )

        session = await self._get_session()
        url = f"{TWELVE_DATA_BASE_URL}{endpoint}"
        
        request_params = params.copy() if params else {}
        request_params["apikey"] = self.api_key

        response_text_snippet = ""
        last_exception: Optional[Exception] = None

        for attempt in range(self.retry_count + 1):
            try:
                if self.verbose_logging:
                    logger.debug(f"TwelveDataPlugin '{self.provider_id}': Requesting {method} {url}, Params: {request_params} (Attempt {attempt+1})")

                async with session.request(method, url, params=request_params) as response:
                    response_text = await response.text()
                    response_text_snippet = response_text[:500]

                    if self.verbose_logging:
                        logger.debug(f"TwelveDataPlugin '{self.provider_id}': Response Status {response.status} from {url}. Body: {response_text_snippet}")
                    
                    # Twelve Data specific error structure: {"code": ..., "message": ..., "status": "error"}
                    parsed_json = None
                    if response.content_type == 'application/json':
                        try:
                            parsed_json = await response.json()
                            if isinstance(parsed_json, dict) and parsed_json.get("status") == "error":
                                error_code = parsed_json.get("code", response.status)
                                error_message = parsed_json.get("message", response_text_snippet)
                                logger.error(f"TwelveDataPlugin '{self.provider_id}': API error {error_code} for {url}. Message: {error_message}")
                                if error_code == 401 or error_code == 403:
                                    raise AuthenticationPluginError(provider_id=self.provider_id, message=f"Twelve Data API Error {error_code}: {error_message}")
                                if error_code == 429:
                                     raise NetworkPluginError(provider_id=self.provider_id, message=f"Twelve Data API Error {error_code} (Rate Limit): {error_message}")
                                raise PluginError(message=f"Twelve Data API Error {error_code}: {error_message}", provider_id=self.provider_id)
                        except Exception: # If parsing error_data fails or it's not JSON
                            pass # Fall through to general status code check
                    
                    # General HTTP errors if not caught by specific JSON error structure
                    if response.status == 401 or response.status == 403:
                        raise AuthenticationPluginError(provider_id=self.provider_id, message=f"HTTP Error {response.status}: {response_text_snippet}")
                    if response.status == 429:
                        raise NetworkPluginError(provider_id=self.provider_id, message=f"HTTP Error 429 (Rate Limit): {response_text_snippet}")

                    response.raise_for_status()
                    
                    if response.status == 204: return {}
                    
                    # If parsed_json is already available from error checking and status is ok, use it.
                    # Otherwise, parse again.
                    return parsed_json if parsed_json and parsed_json.get("status") != "error" else await response.json(content_type=None)


            except (NetworkPluginError, aiohttp.ClientConnectionError, aiohttp.ServerDisconnectedError, asyncio.TimeoutError) as e:
                last_exception = e
                if attempt == self.retry_count:
                    logger.error(f"TwelveDataPlugin '{self.provider_id}': Max retries for {url}. Error: {e}", exc_info=False)
                    raise NetworkPluginError(self.provider_id, f"API call to {url} failed: {e}", e) from e
                delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.5)
                logger.warning(f"TwelveDataPlugin ('{self.provider_id}'): {type(e).__name__} for {url} (Attempt {attempt+1}). Retrying in {delay:.2f}s.")
                await asyncio.sleep(delay)
            except AuthenticationPluginError: raise
            except PluginError: raise # Already specific
            except aiohttp.ClientResponseError as e: # From raise_for_status
                logger.error(f"TwelveDataPlugin '{self.provider_id}': HTTP error {e.status} for {url}: {e.message}. Resp: {response_text_snippet}", exc_info=False)
                if e.status >= 500 and attempt < self.retry_count: # Retry server errors
                    last_exception = e
                    delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.5)
                    logger.warning(f"TwelveDataPlugin ('{self.provider_id}'): HTTP {e.status} (Attempt {attempt+1}). Retrying in {delay:.2f}s.")
                    await asyncio.sleep(delay)
                    continue
                raise PluginError(f"HTTP error {e.status}: {e.message}", self.provider_id, e) from e
            except Exception as e:
                logger.error(f"TwelveDataPlugin '{self.provider_id}': Unexpected error for {url}: {e}. Resp: {response_text_snippet}", exc_info=True)
                last_exception = e
                if attempt == self.retry_count:
                    raise PluginError(f"Unexpected API error: {e}", self.provider_id, e) from e
                delay = self.retry_delay_base * (2 ** attempt)
                await asyncio.sleep(delay)
        
        if last_exception:
            raise PluginError(f"API call failed for {url}. Last: {last_exception}", self.provider_id, last_exception)
        raise PluginError(f"API call failed unexpectedly for {url}", self.provider_id)

    def _map_internal_timeframe_to_twelve(self, internal_timeframe: str) -> str:
        """Maps internal timeframe string to Twelve Data's 'interval' format."""
        # Twelve Data intervals: 1min, 5min, 15min, 30min, 45min, 1h, 2h, 4h, 1day, 1week, 1month
        tf_lower = internal_timeframe.lower()
        mapping = {
            "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "45m": "45min",
            "1h": "1h", "2h": "2h", "4h": "4h",
            "1d": "1day", "d": "1day",
            "1w": "1week", "w": "1week",
            "1mo": "1month", "mo": "1month", "mon": "1month"
        }
        if tf_lower in mapping:
            return mapping[tf_lower]
        
        # Try direct use if it matches their pattern, e.g. "1min", "1hour" (if user used "1hour")
        if tf_lower in ["1min", "5min", "15min", "30min", "45min", "1h", "2h", "4h", "1day", "1week", "1month"]:
            return tf_lower

        logger.warning(f"TwelveDataPlugin: Unmapped internal timeframe '{internal_timeframe}'. Defaulting to '1day'.")
        return "1day" # Fallback

    def _parse_twelve_data_timestamp(self, datetime_str: str) -> int:
        """Parses Twelve Data's datetime string (e.g., "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD") into UTC ms."""
        try:
            # Check for "YYYY-MM-DD HH:MM:SS" format
            dt_obj = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            # Check for "YYYY-MM-DD" format (for daily, weekly, monthly)
            dt_obj = datetime.strptime(datetime_str, "%Y-%m-%d")
        
        # Twelve Data timestamps are typically UTC.
        dt_obj_utc = dt_obj.replace(tzinfo=timezone.utc)
        return int(dt_obj_utc.timestamp() * 1000)

    async def get_symbols(self, market: str) -> List[str]:
        normalized_market = market.lower()
        current_time = time.monotonic()
        
        cached_data, cache_timestamp = self._symbols_cache.get(normalized_market, (None, 0.0))
        if cached_data and (current_time - cache_timestamp < SYMBOLS_CACHE_TTL_SECONDS):
            logger.debug(f"TwelveDataPlugin: Returning symbols for '{normalized_market}' from cache.")
            return cached_data

        endpoint_map = {
            "us_equity": "/stocks",
            "global_equity": "/stocks", # May need country/exchange params
            "forex": "/forex_pairs",
            "crypto": "/cryptocurrencies", # Can also use /cryptocurrency_exchanges
            "index": "/indices",
            "etf": "/etf"
            # Commodities are often accessed differently by TwelveData (e.g. specific symbols, futures)
        }
        if normalized_market not in endpoint_map:
            raise PluginError(f"Unsupported market '{market}' for Twelve Data symbol listing.", self.provider_id)
        
        endpoint = endpoint_map[normalized_market]
        api_params = {}
        # TODO: Add parameters like 'exchange' or 'country' if needed, based on `market` or `self.additional_kwargs`
        # e.g. if market is "us_equity", api_params["country"] = "USA"

        logger.debug(f"TwelveDataPlugin: Fetching symbols for '{normalized_market}' from '{endpoint}'.")
        
        try:
            response_data = await self._request_api(endpoint, params=api_params)
            symbols_list: List[str] = []
            if isinstance(response_data, dict) and "data" in response_data and isinstance(response_data["data"], list):
                for item in response_data["data"]:
                    if isinstance(item, dict) and "symbol" in item:
                        symbols_list.append(item["symbol"])
            elif isinstance(response_data, list): # Some endpoints might return a list directly
                 for item in response_data:
                    if isinstance(item, dict) and "symbol" in item:
                        symbols_list.append(item["symbol"])

            self._symbols_cache[normalized_market] = (symbols_list, current_time)
            logger.info(f"TwelveDataPlugin: Fetched {len(symbols_list)} symbols for '{normalized_market}'.")
            return sorted(list(set(symbols_list)))
        except PluginError as e:
            logger.error(f"TwelveDataPlugin: PluginError fetching symbols for '{market}': {e}", exc_info=False)
            if cached_data: return cached_data
            raise
        except Exception as e:
            logger.error(f"TwelveDataPlugin: Unexpected error fetching symbols for '{market}': {e}", exc_info=True)
            if cached_data: return cached_data
            raise PluginError(f"Unexpected error fetching symbols: {e}", self.provider_id, e) from e

    async def fetch_historical_ohlcv(
        self, symbol: str, timeframe: str,
        since: Optional[int] = None, limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> List[OHLCVBar]:
        twelve_interval = self._map_internal_timeframe_to_twelve(timeframe)
        
        api_params: Dict[str, Any] = {
            "symbol": symbol,
            "interval": twelve_interval,
            "outputsize": limit if limit is not None and limit <= 5000 else await self.get_fetch_ohlcv_limit() # Max 5000
        }
        if params: api_params.update(params) # Allow overriding via passthrough

        if "start_date" not in api_params and since is not None:
            api_params["start_date"] = datetime.fromtimestamp(since / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        
        # If 'until' was passed from orchestrator, it should be in `params` as 'until_ms'
        if params and "until_ms" in params and "end_date" not in api_params:
            api_params["end_date"] = datetime.fromtimestamp(params["until_ms"] / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        elif "end_date" not in api_params: # Default end_date to now if not specified
             api_params["end_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


        logger.debug(f"TwelveDataPlugin: Fetching OHLCV for {symbol} @ {twelve_interval}. API Params: {api_params}")

        try:
            response_data = await self._request_api("/time_series", params=api_params)
            parsed_bars: List[OHLCVBar] = []

            if isinstance(response_data, dict) and "values" in response_data and isinstance(response_data["values"], list):
                for bar_data in response_data["values"]:
                    if not isinstance(bar_data, dict): continue
                    try:
                        ts_ms = self._parse_twelve_data_timestamp(bar_data["datetime"])
                        parsed_bars.append({
                            "timestamp": ts_ms,
                            "open": float(bar_data["open"]),
                            "high": float(bar_data["high"]),
                            "low": float(bar_data["low"]),
                            "close": float(bar_data["close"]),
                            "volume": float(bar_data.get("volume", 0.0)),
                        })
                    except (TypeError, ValueError, KeyError) as e_parse:
                        logger.warning(f"TwelveDataPlugin: Error parsing bar for {symbol}: {bar_data}. Error: {e_parse}. Skipping.", exc_info=False)
            
            # Twelve Data time_series is newest first, so reverse for oldest first
            parsed_bars.reverse() 

            logger.info(f"TwelveDataPlugin: Fetched {len(parsed_bars)} OHLCV bars for {symbol}/{timeframe}.")
            return parsed_bars # DataOrchestrator will apply final filtering/limit
        except PluginError as e:
            if response_data is not None and isinstance(response_data, dict) and response_data.get("status") == "error" and "values" not in response_data :
                logger.info(f"TwelveDataPlugin: No data found (API status error, no values) for {symbol}/{timeframe}. API Params: {api_params}. Message: {response_data.get('message')}")
                return [] # No data for this symbol/range
            raise
        except Exception as e:
            logger.error(f"TwelveDataPlugin: Unexpected error fetching OHLCV for {symbol}: {e}", exc_info=True)
            raise PluginError(f"Unexpected error fetching OHLCV for {symbol}: {e}", self.provider_id, e) from e

    async def fetch_latest_ohlcv(self, symbol: str, timeframe: str = "1m") -> Optional[OHLCVBar]:
        logger.debug(f"TwelveDataPlugin: Fetching latest '{timeframe}' bar for {symbol}.")
        try:
            # Use time_series with a small outputsize to get a recent, complete bar
            # Set end_date to ensure we are looking at very recent data
            now_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            # Look back a bit to ensure data availability
            start_lookback_days = 2 if timeframe in ['1day', '1week', '1month'] else 1
            start_date_str = (datetime.now(timezone.utc) - timedelta(days=start_lookback_days)).strftime("%Y-%m-%d %H:%M:%S")

            api_params_latest = {
                "symbol": symbol,
                "interval": self._map_internal_timeframe_to_twelve(timeframe),
                "outputsize": 5, # Fetch a few recent bars
                "start_date": start_date_str,
                "end_date": now_utc_str
            }
            
            # Re-use fetch_historical_ohlcv as it handles parsing and sorting already
            bars = await self.fetch_historical_ohlcv(symbol, timeframe, params=api_params_latest, limit=5)

            if bars:
                latest_bar = bars[-1] # fetch_historical_ohlcv sorts oldest first now
                logger.info(f"TwelveDataPlugin: Fetched latest '{timeframe}' bar for {symbol} @ {format_timestamp_to_iso(latest_bar['timestamp'])}.")
                return latest_bar
            
            # Fallback: Try /quote endpoint if time_series yields nothing (might be less ideal for a full bar)
            logger.debug(f"TwelveDataPlugin: time_series gave no latest for {symbol}. Trying /quote.")
            quote_data = await self._request_api("/quote", params={"symbol": symbol})
            if isinstance(quote_data, dict) and all(k in quote_data for k in ["open", "high", "low", "close", "timestamp", "volume"]):
                # Convert quote data (which might be for current day) into OHLCVBar
                # Ensure timestamp from /quote is in milliseconds UTC
                ts_ms = int(quote_data["timestamp"]) * 1000 # Assuming /quote timestamp is in seconds
                
                # If quote doesn't have specific OHLC for a "bar", it might be daily summary
                # We might need to infer the bar based on the timeframe requested
                # For simplicity, if timeframe is '1d', this quote might represent the daily bar
                if timeframe == '1d':
                    return {
                        "timestamp": ts_ms,
                        "open": float(quote_data["open"]),
                        "high": float(quote_data["high"]),
                        "low": float(quote_data["low"]),
                        "close": float(quote_data["close"]),
                        "volume": float(quote_data.get("volume", 0.0)),
                    }
            logger.warning(f"TwelveDataPlugin: No latest '{timeframe}' bar found for {symbol} via any method.")
            return None

        except PluginError as e:
            logger.error(f"TwelveDataPlugin: PluginError fetching latest bar for {symbol}/{timeframe}: {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"TwelveDataPlugin: Unexpected error fetching latest bar for {symbol}/{timeframe}: {e}", exc_info=True)
            return None

    async def get_market_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        current_time = time.monotonic()
        cached_data, cache_timestamp = self._market_info_cache.get(symbol, (None, 0.0))

        if cached_data and (current_time - cache_timestamp < MARKET_INFO_CACHE_TTL_SECONDS):
            logger.debug(f"TwelveDataPlugin: Returning market info for '{symbol}' from cache.")
            return cached_data
        
        # Determine endpoint based on likely symbol type (heuristic)
        # TODO: A more robust way would be to know the market type from context
        endpoint = "/profile" # Default for stocks/ETFs
        # if symbol looks like forex (e.g. EUR/USD) or crypto (e.g. BTC/USD)
        # TwelveData doesn't have a direct "profile" for forex/crypto pairs in the same way as stocks.
        # For forex/crypto, the "market info" might just be what's available from symbol list endpoints.
        # For now, we'll primarily support /profile for stock-like symbols.
        
        logger.debug(f"TwelveDataPlugin: Fetching market info (profile) for '{symbol}'.")
        try:
            # /profile typically returns a dict directly
            response_data = await self._request_api(endpoint, params={"symbol": symbol})
            if isinstance(response_data, dict) and "symbol" in response_data:
                self._market_info_cache[symbol] = (response_data, current_time)
                logger.info(f"TwelveDataPlugin: Fetched and cached market info for '{symbol}'.")
                return response_data
            
            logger.warning(f"TwelveDataPlugin: No valid market info dict in response for '{symbol}'. Resp: {str(response_data)[:200]}")
            self._market_info_cache[symbol] = (None, current_time)
            return None
        except PluginError as e:
            # Check if it was a "not found" type of error from the API
            if isinstance(e.original_exception, aiohttp.ClientResponseError) and e.original_exception.status == 400: # Bad Request (often means symbol not found)
                 logger.info(f"TwelveDataPlugin: Market info not found for symbol '{symbol}' (API 400).")
                 self._market_info_cache[symbol] = (None, current_time)
                 return None
            logger.error(f"TwelveDataPlugin: PluginError fetching market info for '{symbol}': {e}", exc_info=False)
            if isinstance(e, AuthenticationPluginError): raise
            return None # For other PluginErrors like network, treat as info not available
        except Exception as e:
            logger.error(f"TwelveDataPlugin: Unexpected error fetching market info for '{symbol}': {e}", exc_info=True)
            return None


    async def validate_symbol(self, symbol: str) -> bool:
        logger.debug(f"TwelveDataPlugin: Validating symbol '{symbol}'.")
        try:
            # A quick way to validate is to fetch a very small piece of data, like a quote.
            # If it succeeds, symbol is likely valid.
            # The /quote endpoint is often cheaper/faster than /profile.
            quote_data = await self._request_api("/quote", params={"symbol": symbol})
            is_valid = isinstance(quote_data, dict) and quote_data.get("status") != "error" and "symbol" in quote_data
            if is_valid and quote_data.get("symbol", "").upper() == symbol.upper():
                return True
            # Try market_info as a fallback if quote failed or was inconclusive
            market_info = await self.get_market_info(symbol) # Uses cache
            return market_info is not None and market_info.get("symbol", "").upper() == symbol.upper()
        except Exception: # Catch all from _request_api or get_market_info if they raise
            logger.debug(f"TwelveDataPlugin: Symbol '{symbol}' failed validation checks. Assuming invalid.")
            return False

    async def get_supported_timeframes(self) -> Optional[List[str]]:
        if self._supported_timeframes_cache is None:
            # These are internal representations that map to Twelve Data's intervals
            self._supported_timeframes_cache = [
                "1m", "5m", "15m", "30m", "45m", 
                "1h", "2h", "4h", 
                "1d", "1w", "1mo"
            ]
        return self._supported_timeframes_cache

    async def get_fetch_ohlcv_limit(self) -> int:
        # Twelve Data time_series outputsize max is 5000
        return self._fetch_limit_cache or 5000 
        
    async def get_supported_features(self) -> Dict[str, bool]:
        return {
            "watch_ticks": False, # Twelve Data has WebSockets, not implemented here
            "fetch_trades": False, # They offer tick data, but trades not focus of this plugin
            "trading_api": False, 
            "get_market_info": True,
            "validate_symbol": True,
            "get_supported_timeframes": True,
            "get_fetch_ohlcv_limit": True,
        }

    async def close(self) -> None:
        logger.info(f"TwelveDataPlugin '{self.provider_id}': Closing instance resources.")
        async with self._session_lock:
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                    logger.debug(f"TwelveDataPlugin '{self.provider_id}': aiohttp.ClientSession closed.")
                except Exception as e_close:
                    logger.error(f"TwelveDataPlugin '{self.provider_id}': Error closing ClientSession: {e_close}", exc_info=True)
            self._session = None
        
        self._symbols_cache.clear()
        self._market_info_cache.clear()
        logger.info(f"TwelveDataPlugin '{self.provider_id}': Session closed and caches cleared.")