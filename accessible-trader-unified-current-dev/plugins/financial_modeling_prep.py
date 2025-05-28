# plugins/financial_modeling_prep.py

import asyncio
import logging
import os
import time
import random # For retry jitter
from datetime import datetime, timezone, date
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

FMP_BASE_URL_V3 = "https://financialmodelingprep.com/api/v3"
# FMP_BASE_URL_V4 = "https://financialmodelingprep.com/api/v4" # Some endpoints might be v4

# Default retry configuration
DEFAULT_FMP_RETRY_COUNT = 3
DEFAULT_FMP_RETRY_DELAY_BASE_S = 1.0

# Cache TTLs (in seconds)
SYMBOLS_CACHE_TTL_SECONDS = 6 * 3600  # 6 hours for symbol lists
MARKET_INFO_CACHE_TTL_SECONDS = 24 * 3600 # 24 hours for profile/details

class FMPPlugin(MarketPlugin):
    plugin_key: str = "financial_modeling_prep"
    # TODO: Review FMP's actual current market coverage. This is an assumption.
    # Supporting 'us_equity' (general stocks), 'forex', and 'crypto'.
    # FMP might treat US and global equities under one umbrella or separate API calls.
    supported_markets: List[str] = ["us_equity", "forex", "crypto", "indices", "commodities"]

    def __init__(
        self,
        provider_id: str, # Expected to be "financial_modeling_prep"
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None, # Not typically used by FMP
        api_passphrase: Optional[str] = None, # Not typically used by FMP
        is_testnet: bool = False, # FMP doesn't have a distinct testnet mode via URL
        request_timeout: int = 30000,
        verbose_logging: bool = False,
        retry_count: int = DEFAULT_FMP_RETRY_COUNT,
        retry_delay_base: float = DEFAULT_FMP_RETRY_DELAY_BASE_S,
        **kwargs: Any
    ):
        if provider_id.lower() != "financial_modeling_prep":
            raise PluginError(
                message=f"FMPPlugin initialized with incorrect provider_id: '{provider_id}'. Expected 'financial_modeling_prep'.",
                provider_id=provider_id
            )

        resolved_api_key = api_key or os.getenv("FMP_API_KEY")

        super().__init__(
            provider_id="fmp",
            api_key=resolved_api_key,
            api_secret=None,
            api_passphrase=None,
            is_testnet=is_testnet, # Stored, but FMP doesn't use a testnet environment
            request_timeout=request_timeout,
            verbose_logging=verbose_logging,
            **kwargs
        )

        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        
        self.retry_count = retry_count
        self.retry_delay_base = retry_delay_base

        # Instance-specific caches
        # Key: market_type (e.g., "us_equity"), Value: (list_of_symbols, timestamp)
        self._symbols_cache: Dict[str, Tuple[Optional[List[str]], float]] = {}
        # Key: symbol_ticker, Value: (market_info_dict, timestamp)
        self._market_info_cache: Dict[str, Tuple[Optional[Dict[str, Any]], float]] = {}
        self._supported_timeframes_cache: Optional[List[str]] = None
        self._fetch_limit_cache: Optional[int] = None # FMP historical limit often depends on plan/timeframe

        if not self.api_key:
            logger.warning(
                f"FMPPlugin for '{self.provider_id}' initialized without an API Key. "
                "Most operations will fail or be severely rate-limited. "
                "Ensure FMP_API_KEY is set in environment or provided."
            )
        logger.info(
            f"FMPPlugin instance initialized. Provider: '{self.provider_id}', API Key Provided: {bool(self.api_key)}."
        )

    @classmethod
    def get_plugin_key(cls) -> str:
        return cls.plugin_key

    @classmethod
    def get_supported_markets(cls) -> List[str]:
        return cls.supported_markets

    @classmethod
    def list_configurable_providers(cls) -> List[str]:
        """FMPPlugin class handles only the 'fmp' provider."""
        return ["fmp"]

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session is None or self._session.closed:
                timeout_seconds = self.request_timeout / 1000.0
                timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                self._session = aiohttp.ClientSession(timeout=timeout)
                logger.debug(f"FMPPlugin '{self.provider_id}': New aiohttp.ClientSession created.")
            return self._session

    async def _request_api(
        self,
        endpoint: str, # Relative endpoint, e.g., "/historical-chart/1min/AAPL"
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
        base_url: str = FMP_BASE_URL_V3
    ) -> Any:
        if not self.api_key:
            raise AuthenticationPluginError(
                provider_id=self.provider_id,
                message="FMP API Key is required for this operation but not configured."
            )

        session = await self._get_session()
        url = f"{base_url}{endpoint}"
        
        request_params = params.copy() if params else {}
        request_params["apikey"] = self.api_key # Add API key to all requests

        response_text_snippet = ""
        last_exception: Optional[Exception] = None

        for attempt in range(self.retry_count + 1):
            try:
                if self.verbose_logging:
                    logger.debug(f"FMPPlugin '{self.provider_id}': Requesting {method} {url}, Params: {request_params} (Attempt {attempt+1})")

                async with session.request(method, url, params=request_params) as response:
                    response_text = await response.text()
                    response_text_snippet = response_text[:500]

                    if self.verbose_logging:
                        logger.debug(f"FMPPlugin '{self.provider_id}': Response Status {response.status} from {url}. Body Snippet: {response_text_snippet}")

                    if response.status == 401 or response.status == 403: # Unauthorized / Forbidden (e.g. invalid API key, no permission)
                        raise AuthenticationPluginError(provider_id=self.provider_id, message=f"FMP API Error {response.status} (Auth/Permission Failed): {response_text_snippet}")
                    
                    if response.status == 429: # Too Many Requests
                        logger.warning(f"FMPPlugin '{self.provider_id}': FMP API Error 429 (Rate Limit Exceeded). Params: {request_params}. Resp: {response_text_snippet}")
                        raise NetworkPluginError(provider_id=self.provider_id, message=f"FMP API Error 429 (Rate Limit Exceeded): {response_text_snippet}")

                    # FMP might return error messages in JSON, e.g. {"Error Message": "..."}
                    if response.content_type == 'application/json':
                        try:
                            error_data = await response.json()
                            if isinstance(error_data, dict) and "Error Message" in error_data:
                                error_message = error_data["Error Message"]
                                logger.error(f"FMPPlugin '{self.provider_id}': API returned error for {url}. Message: {error_message}")
                                # Check for "limit reached" message
                                if "limit reached" in error_message.lower() or "please upgrade your plan" in error_message.lower():
                                     raise NetworkPluginError(provider_id=self.provider_id, message=f"FMP API Error (Limit/Subscription): {error_message}")
                                raise PluginError(message=f"FMP API Error: {error_message}", provider_id=self.provider_id)
                        except Exception:
                            pass # Fall through if error parsing doesn't match
                    
                    response.raise_for_status() # Raises HTTPError for other 4XX, 5XX
                    
                    if response.status == 204: return {} # No content
                    
                    # Check if FMP returned an empty list, which sometimes signifies "not found" or "no data" rather than an error
                    # For example, historical data for a wrong symbol might return []
                    if response_text.strip() == "[]" and response.content_type == 'application/json':
                        logger.debug(f"FMPPlugin '{self.provider_id}': API returned an empty list for {url}. Assuming no data/not found for this request.")
                        return [] # Return empty list to signify no data for this specific call
                        
                    data = await response.json(content_type=None) # content_type=None if FMP sends non-standard JSON type
                    return data

            except (NetworkPluginError, aiohttp.ClientConnectionError, aiohttp.ServerDisconnectedError, asyncio.TimeoutError) as e:
                last_exception = e
                if attempt == self.retry_count:
                    logger.error(f"FMPPlugin '{self.provider_id}': Max retries exhausted for {url}. Last error: {e}", exc_info=False)
                    raise NetworkPluginError(provider_id=self.provider_id, message=f"API call to {url} failed after retries: {e}", original_exception=e) from e
                
                delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.5)
                logger.warning(f"FMPPlugin ('{self.provider_id}'): {type(e).__name__} on {method} {url} (Attempt {attempt+1}/{self.retry_count+1}). Retrying in {delay:.2f}s. Error: {str(e)[:200]}")
                await asyncio.sleep(delay)
            except AuthenticationPluginError: # Non-retryable
                raise
            except PluginError: # Other FMP specific errors already wrapped, non-retryable
                raise
            except aiohttp.ClientResponseError as e:
                logger.error(f"FMPPlugin '{self.provider_id}': HTTP error {e.status} for {url}: {e.message}. Response: {response_text_snippet}", exc_info=False)
                if e.status >= 500 and attempt < self.retry_count: # Retry on server errors
                    last_exception = e
                    delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.5)
                    logger.warning(f"FMPPlugin ('{self.provider_id}'): HTTP {e.status} on {method} {url} (Attempt {attempt+1}/{self.retry_count+1}). Retrying in {delay:.2f}s.")
                    await asyncio.sleep(delay)
                    continue
                raise PluginError(message=f"HTTP error {e.status}: {e.message}", provider_id=self.provider_id, original_exception=e) from e
            except Exception as e:
                logger.error(f"FMPPlugin '{self.provider_id}': Unexpected error requesting {url} (Params: {request_params}): {e}. Response: {response_text_snippet}", exc_info=True)
                last_exception = e
                if attempt == self.retry_count:
                    raise PluginError(message=f"Unexpected API error after retries: {e}", provider_id=self.provider_id, original_exception=e) from e
                delay = self.retry_delay_base * (2 ** attempt)
                await asyncio.sleep(delay)
        
        if last_exception:
            raise PluginError(f"API call failed after all retries for {url}. Last error: {last_exception}", self.provider_id, last_exception)
        raise PluginError(f"API call failed unexpectedly for {url}", self.provider_id)

    def _map_internal_timeframe_to_fmp(self, internal_timeframe: str) -> str:
        """Maps internal timeframe string to FMP's expected format."""
        tf_lower = internal_timeframe.lower()
        # FMP uses "1min", "5min", "15min", "30min", "1hour", "4hour", "daily"
        if tf_lower.endswith('m'): # e.g. "1m", "5m"
            return tf_lower.replace('m', 'min')
        if tf_lower.endswith('h'): # e.g. "1h", "4h"
            return tf_lower.replace('h', 'hour')
        if tf_lower == '1d' or tf_lower == 'd':
            return 'daily'
        # TODO: Add mappings for weekly, monthly if FMP supports them in historical-chart
        # For example, FMP's daily endpoint might be the source for resampling to weekly/monthly if not native.
        logger.warning(f"FMPPlugin: Unmapped internal timeframe '{internal_timeframe}'. Trying to use 'daily'.")
        return 'daily' # Fallback

    def _parse_fmp_timestamp(self, date_str: str) -> int:
        """Parses FMP's date string (e.g., "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD") into UTC ms."""
        try:
            # Try parsing with time first
            dt_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            # Try parsing as date only (for daily bars)
            dt_obj = datetime.strptime(date_str, "%Y-%m-%d")
        
        # Assume FMP timestamps are in US/Eastern or a market-specific time.
        # For simplicity here, we'll assume they can be treated as UTC or that historical
        # chart data from FMP is already adjusted or should be interpreted as such.
        # A more robust solution would involve knowing the exchange timezone for each symbol.
        # If FMP provides UTC or it's safe to assume so:
        dt_obj_utc = dt_obj.replace(tzinfo=timezone.utc)
        return int(dt_obj_utc.timestamp() * 1000)


    async def get_symbols(self, market: str) -> List[str]:
        normalized_market = market.lower()
        current_time = time.monotonic()
        
        cached_data, cache_timestamp = self._symbols_cache.get(normalized_market, (None, 0.0))
        if cached_data and (current_time - cache_timestamp < SYMBOLS_CACHE_TTL_SECONDS):
            logger.debug(f"FMPPlugin '{self.provider_id}': Returning symbols for market '{normalized_market}' from cache.")
            return cached_data

        endpoint = ""
        # TODO: Confirm FMP endpoints for different markets
        if normalized_market == "us_equity" or normalized_market == "global_equity" or normalized_market == "etf":
            endpoint = "/stock/list" # Also lists ETFs
        elif normalized_market == "forex":
            endpoint = "/symbol/available-forex" # Or /forex-currency-pairs
        elif normalized_market == "crypto":
            endpoint = "/symbol/available-cryptocurrencies" # Or /crypto-currency-pairs
        elif normalized_market == "index":
            endpoint = "/symbol/available-indexes"
        elif normalized_market == "commodity":
            endpoint = "/symbol/available-commodities" # Check if this provides tradable symbols for OHLCV
        else:
            raise PluginError(f"Unsupported market '{market}' for FMP symbol listing.", self.provider_id)

        logger.debug(f"FMPPlugin '{self.provider_id}': Fetching symbols for market '{normalized_market}' from endpoint '{endpoint}'.")
        
        try:
            response_data = await self._request_api(endpoint)
            symbols_list: List[str] = []
            if isinstance(response_data, list):
                for item in response_data:
                    if isinstance(item, dict) and "symbol" in item:
                        symbols_list.append(item["symbol"])
                    # For forex/crypto, the structure might be different, e.g., item itself is the symbol string
                    elif isinstance(item, str): # some FMP endpoints return list of strings
                        symbols_list.append(item)
            
            if not symbols_list and isinstance(response_data, dict) and "symbolsList" in response_data: # Older FMP style
                 if isinstance(response_data["symbolsList"], list):
                    for item in response_data["symbolsList"]:
                         if isinstance(item, dict) and "symbol" in item:
                            symbols_list.append(item["symbol"])


            self._symbols_cache[normalized_market] = (symbols_list, current_time)
            logger.info(f"FMPPlugin '{self.provider_id}': Fetched and cached {len(symbols_list)} symbols for market '{normalized_market}'.")
            return sorted(list(set(symbols_list)))
        except PluginError as e:
            logger.error(f"FMPPlugin '{self.provider_id}': PluginError fetching symbols for market '{market}': {e}", exc_info=False)
            if cached_data: return cached_data # Return stale on error
            raise
        except Exception as e:
            logger.error(f"FMPPlugin '{self.provider_id}': Unexpected error fetching symbols for market '{market}': {e}", exc_info=True)
            if cached_data: return cached_data
            raise PluginError(message=f"Unexpected error fetching symbols: {e}", provider_id=self.provider_id, original_exception=e) from e


    async def fetch_historical_ohlcv(
        self, symbol: str, timeframe: str,
        since: Optional[int] = None, limit: Optional[int] = None, # FMP uses date range primarily
        params: Optional[Dict[str, Any]] = None
    ) -> List[OHLCVBar]:
        fmp_tf = self._map_internal_timeframe_to_fmp(timeframe)
        endpoint = f"/historical-chart/{fmp_tf}/{symbol.upper()}" # FMP symbols are often uppercase

        api_params: Dict[str, Any] = {}
        if params: # Allow passthrough of 'from'/'to' if already formatted
            api_params.update(params)

        if since is not None and "from" not in api_params:
            api_params["from"] = datetime.fromtimestamp(since / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
        
        # FMP historical data often requires 'from' and 'to', or fetches a default range.
        # If 'until' (mapped to 'to') is provided in original `params` it will be used.
        # Otherwise, FMP might fetch up to the current date for the given 'from'.
        # The `limit` param is not directly used by FMP's historical-chart; data is filtered post-fetch if needed.
        # If 'until' was passed in the original fetch_ohlcv, it should be in `params`.

        logger.debug(f"FMPPlugin '{self.provider_id}': Fetching OHLCV for {symbol} @ {fmp_tf}. Endpoint: {endpoint}, API Params: {api_params}")

        try:
            response_data = await self._request_api(endpoint, params=api_params)
            parsed_bars: List[OHLCVBar] = []
            if isinstance(response_data, list):
                for bar_data in response_data:
                    if not isinstance(bar_data, dict) or "date" not in bar_data: # FMP usually has "date"
                        logger.warning(f"FMPPlugin '{self.provider_id}': Malformed bar data for {symbol}: {bar_data}. Skipping.")
                        continue
                    try:
                        ts_ms = self._parse_fmp_timestamp(bar_data["date"])
                        parsed_bars.append({
                            "timestamp": ts_ms,
                            "open": float(bar_data["open"]),
                            "high": float(bar_data["high"]),
                            "low": float(bar_data["low"]),
                            "close": float(bar_data["close"]),
                            "volume": float(bar_data.get("volume", 0.0)), # Volume might be missing or named differently for some assets
                        })
                    except (TypeError, ValueError, KeyError) as e_parse:
                        logger.warning(f"FMPPlugin '{self.provider_id}': Error parsing bar for {symbol}: {bar_data}. Error: {e_parse}. Skipping.", exc_info=False)
            
            # FMP historical data is usually newest first, so we sort it to oldest first
            parsed_bars.sort(key=lambda b: b['timestamp'])
            
            # Apply limit post-fetch if specified, as FMP doesn't always take limit for historical ranges
            if limit is not None and len(parsed_bars) > limit:
                 if since is None: # If it was a "latest N" type request (approximated by range)
                    parsed_bars = parsed_bars[-limit:]
                 else: # If fetching from a specific 'since', take the first N
                    parsed_bars = parsed_bars[:limit]

            logger.info(f"FMPPlugin '{self.provider_id}': Fetched {len(parsed_bars)} OHLCV bars for {symbol}/{timeframe} (FMP TF: {fmp_tf}).")
            return parsed_bars
        except PluginError as e:
            if "empty list" in str(e) or (e.original_exception and "[]" in str(e.original_exception)): # If _request_api returned []
                logger.info(f"FMPPlugin '{self.provider_id}': No data found (empty list from API) for {symbol}/{timeframe}. API Params: {api_params}")
                return []
            raise
        except Exception as e:
            logger.error(f"FMPPlugin '{self.provider_id}': Unexpected error in fetch_historical_ohlcv for {symbol}: {e}", exc_info=True)
            raise PluginError(message=f"Unexpected error fetching OHLCV for {symbol}: {e}", provider_id=self.provider_id, original_exception=e) from e

    async def fetch_latest_ohlcv(self, symbol: str, timeframe: str = "1m") -> Optional[OHLCVBar]:
        logger.debug(f"FMPPlugin '{self.provider_id}': Fetching latest '{timeframe}' bar for {symbol}.")
        
        # Option 1: Use /quote endpoint (might be daily summary or real-time quote, not always a full bar)
        # Option 2: Fetch historical data with limit=1 (more reliable for a full bar)
        try:
            # For latest, fetch a small number of recent bars and take the last one.
            # FMP's /historical-chart might be best. Use a small lookback.
            # 'until' is implicitly now. We need a 'from' date.
            now = datetime.now(timezone.utc)
            from_date_for_latest = (now - timedelta(days=5)).strftime("%Y-%m-%d") # Look back a few days for safety
            to_date_for_latest = now.strftime("%Y-%m-%d")

            fmp_tf = self._map_internal_timeframe_to_fmp(timeframe)
            # Fetch more than 1 bar in case the very latest is partial or to ensure we get a completed one.
            # Let's try to get last ~5 bars of the timeframe. The post-fetch limit in historical will handle it.
            bars = await self.fetch_historical_ohlcv(
                symbol, timeframe, 
                # `since` is not directly used by FMP, but we use `from` and `to`
                params={"from": from_date_for_latest, "to": to_date_for_latest}, 
                limit=5 # Fetch a few bars to pick the latest
            )
            if bars:
                latest_bar = bars[-1] # Last bar in the sorted list
                logger.info(f"FMPPlugin '{self.provider_id}': Fetched latest '{timeframe}' bar for {symbol} @ {format_timestamp_to_iso(latest_bar['timestamp'])}.")
                return latest_bar
            logger.warning(f"FMPPlugin '{self.provider_id}': No latest '{timeframe}' bar for {symbol} from historical fetch.")
            return None
        except PluginError as e:
            logger.error(f"FMPPlugin '{self.provider_id}': PluginError fetching latest bar for {symbol}/{timeframe}: {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"FMPPlugin '{self.provider_id}': Unexpected error fetching latest bar for {symbol}/{timeframe}: {e}", exc_info=True)
            return None


    async def get_market_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        current_time = time.monotonic()
        cached_data, cache_timestamp = self._market_info_cache.get(symbol, (None, 0.0))

        if cached_data and (current_time - cache_timestamp < MARKET_INFO_CACHE_TTL_SECONDS):
            logger.debug(f"FMPPlugin '{self.provider_id}': Returning market info for '{symbol}' from cache.")
            return cached_data

        # TODO: Determine correct endpoint based on symbol type (equity, forex, crypto)
        # Assuming /profile for equities. Other asset types might need different endpoints.
        endpoint = f"/profile/{symbol.upper()}" # For equities
        # For forex/crypto, FMP might not have a dedicated "profile" endpoint.
        # We might need to infer this from the symbol list or general API knowledge.

        logger.debug(f"FMPPlugin '{self.provider_id}': Fetching market info (profile) for '{symbol}'.")
        try:
            response_data = await self._request_api(endpoint)
            # FMP /profile usually returns a list with one item
            if isinstance(response_data, list) and len(response_data) > 0:
                market_details = response_data[0]
                self._market_info_cache[symbol] = (market_details, current_time)
                logger.info(f"FMPPlugin '{self.provider_id}': Fetched and cached market info for '{symbol}'.")
                return market_details
            elif isinstance(response_data, dict) and "symbol" in response_data: # Direct dict response
                self._market_info_cache[symbol] = (response_data, current_time)
                logger.info(f"FMPPlugin '{self.provider_id}': Fetched and cached market info (direct dict) for '{symbol}'.")
                return response_data
            
            logger.warning(f"FMPPlugin '{self.provider_id}': No 'results' or unexpected format in market info response for '{symbol}'. Resp: {str(response_data)[:200]}")
            self._market_info_cache[symbol] = (None, current_time) # Cache miss
            return None
        except PluginError as e:
            if "empty list" in str(e).lower() or "not found" in str(e).lower() or (hasattr(e.original_exception, 'status') and isinstance(e.original_exception, aiohttp.ClientResponseError) and e.original_exception.status == 404):
                 logger.info(f"FMPPlugin '{self.provider_id}': Market info not found for symbol '{symbol}'.")
                 self._market_info_cache[symbol] = (None, current_time)
                 return None
            logger.error(f"FMPPlugin '{self.provider_id}': PluginError fetching market info for '{symbol}': {e}", exc_info=False)
            if isinstance(e, AuthenticationPluginError): raise
            return None
        except Exception as e:
            logger.error(f"FMPPlugin '{self.provider_id}': Unexpected error fetching market info for '{symbol}': {e}", exc_info=True)
            return None

    async def validate_symbol(self, symbol: str) -> bool:
        logger.debug(f"FMPPlugin '{self.provider_id}': Validating symbol '{symbol}'.")
        try:
            market_info = await self.get_market_info(symbol)
            # FMP profile data has an "exchange" or "exchangeShortName".
            # If info is returned, and not explicitly "delisted", assume active.
            # FMP's symbol list endpoints are usually for "available" symbols.
            if market_info and market_info.get("symbol") == symbol.upper():
                 # Add more checks if FMP provides an "active" or "status" field
                return True
            return False
        except Exception:
            logger.debug(f"FMPPlugin '{self.provider_id}': Symbol '{symbol}' not found or error during validation. Assuming invalid.")
            return False

    async def get_supported_timeframes(self) -> Optional[List[str]]:
        if self._supported_timeframes_cache is None:
            # These are common internal representations this plugin can map to FMP.
            # FMP's /historical-chart endpoint supports: 1min, 5min, 15min, 30min, 1hour, 4hour, daily
            self._supported_timeframes_cache = [
                "1m", "5m", "15m", "30m", "1h", "4h", "1d"
            ] # Your internal mapping will convert these.
        return self._supported_timeframes_cache

    async def get_fetch_ohlcv_limit(self) -> int:
        if self._fetch_limit_cache is None:
            # FMP's historical data API doesn't typically use a 'limit' parameter in the same way
            # CCXT or others do. It fetches by date range.
            # For practical purposes, if we need to page or limit, we do it post-fetch or by adjusting date range.
            # Let's set a high conceptual limit, as the real limit is date range + plan.
            self._fetch_limit_cache = 5000 # Arbitrary high number, actual limit is by date range/FMP plan.
        return self._fetch_limit_cache
        
    async def get_supported_features(self) -> Dict[str, bool]:
        return {
            "watch_ticks": False, # FMP has WebSockets but this REST plugin doesn't implement them
            "fetch_trades": False, # FMP might have trades, but not implemented here
            "trading_api": False, 
            "get_market_info": True,
            "validate_symbol": True,
            "get_supported_timeframes": True,
            "get_fetch_ohlcv_limit": True, # Though it's more of a conceptual limit for paging
        }

    async def close(self) -> None:
        logger.info(f"FMPPlugin '{self.provider_id}': Closing instance resources.")
        async with self._session_lock:
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                    logger.debug(f"FMPPlugin '{self.provider_id}': aiohttp.ClientSession closed.")
                except Exception as e_close:
                    logger.error(f"FMPPlugin '{self.provider_id}': Error closing ClientSession: {e_close}", exc_info=True)
            self._session = None
        
        self._symbols_cache.clear()
        self._market_info_cache.clear()
        logger.info(f"FMPPlugin '{self.provider_id}': Session closed and caches cleared.")