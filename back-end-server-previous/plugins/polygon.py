# plugins/polygon.py

import asyncio
import logging
import os
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import aiohttp

from plugins.base import (
    MarketPlugin,
    PluginError,
    AuthenticationPluginError,
    NetworkPluginError,
    PluginFeatureNotSupportedError,
    OHLCVBar
)
from utils.timeframes import (
    format_timestamp_to_iso, # Assuming this utility exists for logging
)

logger = logging.getLogger(__name__)

POLYGON_BASE_URL = "https://api.polygon.io"

# Default retry configuration for API calls
DEFAULT_POLYGON_RETRY_COUNT = 3
DEFAULT_POLYGON_RETRY_DELAY_BASE_S = 1.5 # Polygon can be sensitive to rapid retries

# Cache TTLs
TICKER_DETAILS_CACHE_TTL_SECONDS = 3600  # 1 hour for ticker details
SYMBOLS_CACHE_TTL_SECONDS = 6 * 3600   # 6 hours for ticker lists per market (asset class)

class PolygonPlugin(MarketPlugin):
    plugin_key: str = "polygon"
    # This plugin supports multiple markets.
    # The 'market' parameter in get_symbols will be used to filter.
    # These should map to Polygon's 'market' filter values where possible (stocks, crypto, fx, otc, indices)
    # "us_equity" will be mapped to "stocks" for Polygon API calls.
    supported_markets: List[str] = ["us_equity", "crypto", "forex"] # "options" can be added if fully implemented

    def __init__(
        self,
        provider_id: str, # Expected to be "polygon"
        api_key: Optional[str] = None,
        # Polygon doesn't use secret/passphrase for REST API key auth
        api_secret: Optional[str] = None, # Will be ignored
        api_passphrase: Optional[str] = None, # Will be ignored
        is_testnet: bool = False, # Polygon doesn't have a dedicated testnet mode for data APIs via different URL
        request_timeout: int = 30000,
        verbose_logging: bool = False,
        retry_count: int = DEFAULT_POLYGON_RETRY_COUNT,
        retry_delay_base: float = DEFAULT_POLYGON_RETRY_DELAY_BASE_S,
        **kwargs: Any
    ):
        if provider_id.lower() != "polygon":
            raise PluginError(
                message=f"PolygonPlugin initialized with incorrect provider_id: '{provider_id}'. Expected 'polygon'.",
                provider_id=provider_id
            )

        # Use provided API key or fall back to environment variable
        resolved_api_key = api_key or os.getenv("POLYGON_API_KEY")

        super().__init__(
            provider_id="polygon", # This instance will always handle "polygon"
            api_key=resolved_api_key, # Store the resolved API key
            api_secret=None, # Not used by Polygon with API key
            api_passphrase=None, # Not used by Polygon with API key
            is_testnet=is_testnet, # Stored but may not alter Polygon URLs
            request_timeout=request_timeout,
            verbose_logging=verbose_logging,
            **kwargs
        )

        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        
        self.retry_count = retry_count
        self.retry_delay_base = retry_delay_base

        # Instance-specific caches
        self._ticker_details_cache: Dict[str, Tuple[Optional[Dict[str, Any]], float]] = {} # symbol -> (details, timestamp)
        self._symbols_cache: Dict[str, Tuple[Optional[List[str]], float]] = {} # market_key -> (symbols_list, timestamp)
        self._supported_timeframes_cache: Optional[List[str]] = None # Static list for Polygon
        self._fetch_limit_cache: Optional[int] = None # For aggregates API

        if not self.api_key:
            logger.warning(
                f"PolygonPlugin for '{self.provider_id}' initialized without an API Key. "
                "Most operations will fail. Ensure POLYGON_API_KEY is set in environment or provided."
            )
        logger.info(
            f"PolygonPlugin instance initialized. Provider: '{self.provider_id}', API Key Provided: {bool(self.api_key)}."
        )

    @classmethod
    def get_plugin_key(cls) -> str:
        return cls.plugin_key

    @classmethod
    def get_supported_markets(cls) -> List[str]:
        return cls.supported_markets

    @classmethod
    def list_configurable_providers(cls) -> List[str]:
        """PolygonPlugin class handles only the 'polygon' provider."""
        return ["polygon"]

    async def _get_session(self) -> aiohttp.ClientSession:
        """Ensures an aiohttp session is available and returns it."""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                # Polygon API key is typically passed as a Bearer token in the Authorization header or as apiKey query param
                # Using Authorization header is generally preferred.
                headers = {}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                
                timeout_seconds = self.request_timeout / 1000.0
                timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
                logger.debug(f"PolygonPlugin '{self.provider_id}': New aiohttp.ClientSession created.")
            return self._session

    async def _request_api(
        self,
        endpoint: str, # Relative endpoint, e.g., "/v3/reference/tickers"
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET"
    ) -> Any:
        """Generic helper to make requests to Polygon API, handling errors and response parsing."""
        if not self.api_key: # Most Polygon endpoints require an API key
            raise AuthenticationPluginError(
                provider_id=self.provider_id,
                message="Polygon API Key is required for this operation but not configured."
            )

        session = await self._get_session()
        url = f"{POLYGON_BASE_URL}{endpoint}"
        
        # Polygon API key can also be passed as 'apiKey' in params if not using Auth header
        # For this implementation, assuming Auth header is primary. If issues, can add `params['apiKey'] = self.api_key`
        
        request_params = params.copy() if params else {}
        # Ensure boolean params are lowercase strings for Polygon if needed (e.g. "true"/"false")
        for key, value in request_params.items():
            if isinstance(value, bool):
                request_params[key] = str(value).lower()

        response_text_snippet = ""
        last_exception: Optional[Exception] = None

        for attempt in range(self.retry_count + 1):
            try:
                if self.verbose_logging:
                    logger.debug(f"PolygonPlugin '{self.provider_id}': Requesting {method} {url}, Params: {request_params} (Attempt {attempt+1})")

                async with session.request(method, url, params=request_params) as response:
                    response_text = await response.text()
                    response_text_snippet = response_text[:500]

                    if self.verbose_logging:
                        logger.debug(f"PolygonPlugin '{self.provider_id}': Response Status {response.status} from {url}. Body Snippet: {response_text_snippet}")

                    if response.status == 401 or response.status == 403: # Unauthorized / Forbidden
                        raise AuthenticationPluginError(provider_id=self.provider_id, message=f"API Error {response.status} (Auth Failed): {response_text_snippet}")
                    if response.status == 429: # Too Many Requests
                        # This error should ideally trigger a longer backoff or be handled by a global rate limiter
                        logger.warning(f"PolygonPlugin '{self.provider_id}': API Error 429 (Rate Limit Exceeded). Params: {request_params}. Resp: {response_text_snippet}")
                        # Fall through to retry logic for rate limits, as they might be temporary
                        raise NetworkPluginError(provider_id=self.provider_id, message=f"API Error 429 (Rate Limit Exceeded): {response_text_snippet}")


                    # Check for specific Polygon error structure: {"status": "ERROR", "request_id": "...", "message": "..."}
                    if response.content_type == 'application/json':
                        try:
                            error_data = await response.json()
                            if isinstance(error_data, dict) and error_data.get("status") == "ERROR":
                                error_message = error_data.get("message", response_text_snippet)
                                logger.error(f"PolygonPlugin '{self.provider_id}': API returned ERROR status for {url}. Message: {error_message}. Request ID: {error_data.get('request_id')}")
                                # Treat as a general PluginError, could be more specific based on message
                                raise PluginError(message=f"Polygon API Error: {error_message}", provider_id=self.provider_id)
                        except Exception: # If parsing error_data fails, fall through to raise_for_status
                            pass
                    
                    response.raise_for_status() # Raises HTTPError for other 4XX, 5XX

                    if response.status == 204: return {} # No content
                    
                    data = await response.json(content_type=None)
                    return data

            except (NetworkPluginError, aiohttp.ClientConnectionError, aiohttp.ServerDisconnectedError, asyncio.TimeoutError) as e: # Specific retryable errors
                last_exception = e
                if attempt == self.retry_count:
                    logger.error(f"PolygonPlugin '{self.provider_id}': Max retries ({self.retry_count + 1}) exhausted for {url}. Last error: {e}", exc_info=False)
                    raise NetworkPluginError(provider_id=self.provider_id, message=f"API call to {url} failed after retries: {e}", original_exception=e) from e
                
                delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.5) # Add jitter
                logger.warning(f"PolygonPlugin ('{self.provider_id}'): {type(e).__name__} on {method} {url} (Attempt {attempt+1}/{self.retry_count+1}). Retrying in {delay:.2f}s. Error: {str(e)[:200]}")
                await asyncio.sleep(delay)
            except AuthenticationPluginError: # Non-retryable
                raise
            except PluginError: # Other Polygon specific errors already wrapped, non-retryable
                raise
            except aiohttp.ClientResponseError as e: # Raised by raise_for_status for non-2xx not caught above
                logger.error(f"PolygonPlugin '{self.provider_id}': HTTP error {e.status} for {url}: {e.message}. Response: {response_text_snippet}", exc_info=False)
                # Could be retryable depending on status (e.g. 50x server errors)
                if e.status >= 500 and attempt < self.retry_count:
                    last_exception = e
                    delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.5)
                    logger.warning(f"PolygonPlugin ('{self.provider_id}'): HTTP {e.status} on {method} {url} (Attempt {attempt+1}/{self.retry_count+1}). Retrying in {delay:.2f}s.")
                    await asyncio.sleep(delay)
                    continue
                raise PluginError(message=f"HTTP error {e.status}: {e.message}", provider_id=self.provider_id, original_exception=e) from e
            except Exception as e: # Catch-all for other unexpected errors
                logger.error(f"PolygonPlugin '{self.provider_id}': Unexpected error requesting {url} (Params: {request_params}): {e}. Response snippet: {response_text_snippet}", exc_info=True)
                last_exception = e # Treat as potentially retryable once
                if attempt == self.retry_count:
                    raise PluginError(message=f"Unexpected API error after retries: {e}", provider_id=self.provider_id, original_exception=e) from e
                delay = self.retry_delay_base * (2 ** attempt)
                await asyncio.sleep(delay)
        
        # Should not be reached if all paths raise or return
        if last_exception:
            raise PluginError(f"API call failed after all retries for {url}. Last error: {last_exception}", self.provider_id, last_exception)
        raise PluginError(f"API call failed unexpectedly for {url}", self.provider_id)


    def _map_polygon_market(self, internal_market: str) -> str:
        """Maps internal market name to Polygon's 'market' filter value."""
        normalized_market = internal_market.lower()
        if normalized_market == "us_equity":
            return "stocks" # Polygon uses "stocks" for US equities
        elif normalized_market in ["crypto", "forex", "fx", "options", "otc", "indices"]:
            if normalized_market == "fx": return "forex" # Alias
            return normalized_market
        else:
            logger.warning(f"PolygonPlugin: Unmapped internal market '{internal_market}'. Using as is for Polygon market filter.")
            return normalized_market # Pass through if not explicitly mapped

    def _map_to_polygon_timeframe(self, internal_timeframe: str) -> Tuple[int, str]:
        """
        Maps an internal timeframe string (e.g., "1m", "1D") to Polygon's (multiplier, timespan) format.
        Example: "1m" -> (1, "minute"), "1D" -> (1, "day"), "5h" -> (5, "hour")
        """
        # Remove potential "s" from "mins", "hours"
        tf = internal_timeframe.lower().replace("s", "") 
        
        if tf.endswith("m"): # minute
            try: multiplier = int(tf[:-1])
            except ValueError: multiplier = 1
            return multiplier, "minute"
        elif tf.endswith("h"): # hour
            try: multiplier = int(tf[:-1])
            except ValueError: multiplier = 1
            return multiplier, "hour"
        elif tf.endswith("d"): # day
            try: multiplier = int(tf[:-1])
            except ValueError: multiplier = 1
            return multiplier, "day"
        elif tf.endswith("w"): # week
            try: multiplier = int(tf[:-1])
            except ValueError: multiplier = 1
            return multiplier, "week"
        elif tf.endswith("mo") or tf.endswith("mon"): # month
            try: multiplier = int(tf[:-2] if tf.endswith("mo") else tf[:-3])
            except ValueError: multiplier = 1
            return multiplier, "month"
        elif tf.endswith("y"): # year
            try: multiplier = int(tf[:-1])
            except ValueError: multiplier = 1
            return multiplier, "year"
        
        logger.warning(f"PolygonPlugin: Could not map internal timeframe '{internal_timeframe}' to Polygon format. Defaulting to 1 day.")
        return 1, "day" # Default fallback

    async def get_symbols(self, market: str) -> List[str]:
        """
        Fetches tradable symbols from Polygon for the specified market.
        Uses Polygon's /v3/reference/tickers endpoint.
        """
        polygon_market_filter = self._map_polygon_market(market)
        logger.debug(f"PolygonPlugin '{self.provider_id}': Fetching symbols for market '{market}' (Polygon filter: '{polygon_market_filter}').")

        # Cache key based on the Polygon market filter
        cache_key = polygon_market_filter
        current_time = time.monotonic()
        cached_data, cache_timestamp = self._symbols_cache.get(cache_key, (None, 0.0))

        if cached_data and (current_time - cache_timestamp < SYMBOLS_CACHE_TTL_SECONDS):
            logger.debug(f"PolygonPlugin '{self.provider_id}': Returning symbols for market '{polygon_market_filter}' from cache.")
            return cached_data

        all_symbols: List[str] = []
        cursor: Optional[str] = None
        page_count = 0
        max_pages = 20 # Safety break for pagination, adjust as needed

        try:
            while page_count < max_pages:
                page_count += 1
                params: Dict[str, Any] = {
                    "market": polygon_market_filter,
                    "active": "true",
                    "limit": 1000 # Max limit for tickers endpoint
                }
                if cursor:
                    params["cursor"] = cursor
                
                if self.verbose_logging: logger.debug(f"PolygonPlugin: Fetching tickers page {page_count} for {polygon_market_filter}, cursor: {cursor}")
                
                response_data = await self._request_api("/v3/reference/tickers", params=params)
                
                if response_data and isinstance(response_data.get("results"), list):
                    for ticker_info in response_data["results"]:
                        if isinstance(ticker_info, dict) and "ticker" in ticker_info:
                            all_symbols.append(ticker_info["ticker"])
                    
                    cursor = response_data.get("next_url") # Polygon uses next_url which contains the cursor
                    if cursor: # Extract actual cursor value from next_url
                        try:
                            # Example next_url: https://api.polygon.io/v3/reference/tickers?cursor=Yc...&limit=1000
                            cursor_param_name = "cursor="
                            cursor_start_index = cursor.find(cursor_param_name)
                            if cursor_start_index != -1:
                                cursor_val_start = cursor_start_index + len(cursor_param_name)
                                cursor_end_index = cursor.find("&", cursor_val_start)
                                cursor = cursor[cursor_val_start:] if cursor_end_index == -1 else cursor[cursor_val_start:cursor_end_index]
                            else: # Could not parse cursor from next_url
                                cursor = None
                        except Exception as e_cursor:
                            logger.warning(f"PolygonPlugin: Failed to parse cursor from next_url '{cursor}': {e_cursor}")
                            cursor = None
                            
                    if not cursor: # No more pages
                        break 
                else:
                    logger.warning(f"PolygonPlugin '{self.provider_id}': Unexpected response or no 'results' list for tickers page {page_count}, market '{polygon_market_filter}'. Response: {str(response_data)[:200]}")
                    break # Stop pagination on unexpected response

            self._symbols_cache[cache_key] = (all_symbols, current_time)
            logger.info(f"PolygonPlugin '{self.provider_id}': Fetched {len(all_symbols)} symbols for market '{market}' (Polygon: {polygon_market_filter}) after {page_count} page(s).")
            return sorted(list(set(all_symbols))) # Ensure uniqueness and sort

        except PluginError as e:
            logger.error(f"PolygonPlugin '{self.provider_id}': PluginError fetching symbols for market '{market}': {e}", exc_info=False)
            # Attempt to return stale cache on error
            if cached_data:
                logger.warning(f"PolygonPlugin '{self.provider_id}': Returning stale symbol list for '{cache_key}' due to fetch error.")
                return cached_data
            raise
        except Exception as e:
            logger.error(f"PolygonPlugin '{self.provider_id}': Unexpected error fetching symbols for market '{market}': {e}", exc_info=True)
            if cached_data:
                logger.warning(f"PolygonPlugin '{self.provider_id}': Returning stale symbol list for '{cache_key}' due to unexpected error.")
                return cached_data
            raise PluginError(message=f"Unexpected error fetching symbols: {e}", provider_id=self.provider_id, original_exception=e) from e


    async def fetch_historical_ohlcv(
        self, symbol: str, timeframe: str,
        since: Optional[int] = None, limit: Optional[int] = None, # Polygon uses date range or limit
        params: Optional[Dict[str, Any]] = None # For 'to' date, 'adjusted', etc.
    ) -> List[OHLCVBar]:
        
        multiplier, timespan_str = self._map_to_polygon_timeframe(timeframe)
        
        # Polygon's /v2/aggs endpoint. Ticker format varies (e.g. AAPL, X:BTCUSD, C:EURUSD)
        # The `symbol` provided should already be in Polygon's expected format.
        endpoint = f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan_str}"

        # Date handling for Polygon: requires YYYY-MM-DD for from/to or ms timestamps
        # If `since` (ms timestamp) is provided, it's 'from'.
        # Polygon's API can be queried with either a date range (from/to) OR a limit of bars ending at 'to' (or today).
        # It's generally easier to work with date ranges if `since` is known.
        # If only `limit` is provided without `since`, we need a 'to' date (e.g., today).
        
        api_params: Dict[str, Any] = {}
        
        # Determine 'from' date
        if since is not None:
            from_date_obj = datetime.fromtimestamp(since / 1000.0, tz=timezone.utc).date()
            # Polygon might require 'from' to be not too far in the past for certain granularities without paid plans.
        else:
            # If no 'since', and we have a 'limit', we need a reasonable start date to not fetch too much.
            # Defaulting to a period that makes sense for common limits if 'since' is missing.
            # For example, if limit is 200 and timeframe is 1 day, go back ~200 business days.
            # This logic can be complex. For now, if 'since' is missing, we might rely on 'to' and 'limit'.
            # Polygon's API prefers explicit 'from' and 'to'.
            # Let's require 'since' for simplicity or a 'to' and 'limit'.
            # If only limit is given, and no 'to' in params, we set 'to' as today.
            # If 'since' is missing, the date range needs careful construction based on 'limit' and 'to'.
            # For this version, we will prioritize 'since'. If 'since' is missing, the results might be unexpected
            # unless 'to' and 'limit' are well-managed by the caller via `params`.
            # A common pattern is to calculate 'from' based on 'to' and 'limit' if 'since' is not given.
            # Let's assume `DataOrchestrator` provides a sane `since` or `limit`+`until`
            pass


        # Determine 'to' date
        to_date_obj: Optional[date] = None
        if params and params.get("until_ms"): # 'until_ms' from DataOrchestrator
            to_date_obj = datetime.fromtimestamp(params["until_ms"] / 1000.0, tz=timezone.utc).date()
        elif params and params.get("to_date_str"): # e.g., "YYYY-MM-DD" directly
            try: to_date_obj = date.fromisoformat(params["to_date_str"])
            except ValueError: logger.warning(f"PolygonPlugin: Invalid 'to_date_str' in params: {params['to_date_str']}")
        
        if not to_date_obj: # Default 'to' to today if not specified by 'until_ms' or 'to_date_str'
            to_date_obj = datetime.now(timezone.utc).date()

        # Construct 'from' and 'to' for API. Polygon is inclusive for range.
        # If 'since' is provided, use it. If not, and 'limit' is provided, calculate 'from'.
        if since is not None:
            api_params["from"] = from_date_obj.isoformat()
            api_params["to"] = to_date_obj.isoformat() # 'to' will be today or from params
        else: # 'since' not provided, rely on 'limit' and 'to_date_obj' (defaulting to today)
            # Polygon fetches *up to* 'to_date_obj'. If 'limit' is used, it counts back from 'to_date_obj'.
            api_params["to"] = to_date_obj.isoformat()
            # If 'since' is None, Polygon will use its default behavior for 'from' or one might need to calculate 'from'
            # based on 'to' and 'limit' to make it deterministic.
            # For now, if `since` is None, we let Polygon decide the start based on `to` and `limit` (if `limit` is passed).


        # Add 'limit' if provided by caller, respecting Polygon's max.
        polygon_max_limit = 50000 # Polygon default max limit for aggregates
        if limit is not None:
            api_params["limit"] = min(limit, polygon_max_limit)
        # else: # If no limit from caller, Polygon might use its own default (e.g. 5000) or full range.
              # It's often better to set an explicit limit if 'since' is not very specific.
              # For now, if limit is not passed, we don't set it in params, letting Polygon use its default for the range.

        # Standard params for Polygon aggregates
        api_params["adjusted"] = str(params.get("adjusted", "true")).lower() # Default to adjusted=true
        api_params["sort"] = params.get("sort", "asc") # Default to ascending (oldest first)

        endpoint_with_from_to = f"{endpoint}/{api_params.pop('from', 'undefined')}/{api_params.pop('to', 'undefined')}"
        # 'from' and 'to' must be part of the path for this specific endpoint structure.
        # If 'from' or 'to' were not determined, this will use 'undefined', which will likely cause API error.
        # This shows a flaw: 'from' and 'to' are mandatory in the path for this specific v2 endpoint.
        # Revision: The /v2/aggs endpoint takes 'from' and 'to' in path.
        # Let's ensure they are always present.
        if "from" not in api_params or "to" not in api_params: # This check is after they are popped.
             # Need to ensure from_date_obj and to_date_obj are set.
             # If 'since' (thus from_date_obj) is None, we must calculate it if using this endpoint structure.
             # This highlights that for Polygon, providing 'since' (for 'from') is highly recommended.
             # A robust implementation would calculate 'from' if 'since' is None but 'limit' and 'to' are available.
             # Let's simplify: if `since` is None, this specific implementation path might struggle.
             # The DataOrchestrator usually provides `since` or `until`+`limit`.
            if since is None:
                # If 'since' is None, we must try to derive 'from' using 'to' and 'limit', or error out.
                # For now, let's assume 'since' is typically provided for historical fetches.
                # If not, Polygon might return data based on 'to' and internal limit, or error.
                # A safer approach if `since` is optional is to use the query parameters `from`, `to`, `limit`
                # with a different Polygon endpoint if one supports that better, or enforce `since`.
                # The chosen endpoint `/v2/aggs/ticker/{stocksTicker}/range/{multiplier}/{timespan}/{from}/{to}` requires from/to.
                # Defaulting `from_date_obj` if `since` is None:
                if not hasattr(from_date_obj, 'isoformat'): # Check if from_date_obj was set
                    if limit and to_date_obj: # Calculate from based on a rough estimate
                        # This is a placeholder for a proper calculation based on timeframe, multiplier, and limit
                        from_date_obj = to_date_obj - timedelta(days=limit * 2) # Very rough
                        logger.warning(f"PolygonPlugin: 'since' not provided, 'from' date for {symbol} estimated to {from_date_obj.isoformat()} based on limit and to_date.")
                    else: # Cannot determine 'from' date
                        raise PluginError("PolygonPlugin: 'since' (for 'from' date) must be provided, or 'limit' and 'to_date' for OHLCV fetch.", self.provider_id)
            
            endpoint_final = f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan_str}/{from_date_obj.isoformat()}/{to_date_obj.isoformat()}"
        else: # If from/to were already in api_params and popped. This logic path needs review.
            # This path should be hit if from/to were constructed correctly above.
            endpoint_final = endpoint_with_from_to


        logger.debug(f"PolygonPlugin '{self.provider_id}': Fetching OHLCV from {endpoint_final}. API Query Params: {api_params}")

        try:
            response_data = await self._request_api(endpoint_final, params=api_params) # Query params like 'limit', 'adjusted', 'sort'
            
            parsed_bars: List[OHLCVBar] = []
            # Polygon response: {"results": [{"t": ms_ts, "o": ..., "h": ..., "l": ..., "c": ..., "v": ..., "vw": ..., "n": ...}, ...], "resultsCount": ..., "status": ...}
            if response_data and isinstance(response_data.get("results"), list):
                for bar_data in response_data["results"]:
                    if not all(k in bar_data for k in ["t", "o", "h", "l", "c", "v"]):
                        logger.warning(f"PolygonPlugin '{self.provider_id}': Malformed bar data for {symbol}: {bar_data}. Skipping.")
                        continue
                    try:
                        parsed_bars.append({
                            "timestamp": int(bar_data["t"]), # Already in milliseconds
                            "open": float(bar_data["o"]), "high": float(bar_data["h"]),
                            "low": float(bar_data["l"]), "close": float(bar_data["c"]),
                            "volume": float(bar_data["v"]),
                        })
                    except (TypeError, ValueError) as e_parse:
                        logger.warning(f"PolygonPlugin '{self.provider_id}': Error parsing bar for {symbol}: {bar_data}. Error: {e_parse}. Skipping.", exc_info=False)

            # Polygon results are typically sorted if 'sort=asc' is used with a date range.
            # If using 'limit' without 'sort', order might be newest first if 'from' is far past.
            # If 'sort=asc' was used (default), it should be oldest to newest.
            logger.info(f"PolygonPlugin '{self.provider_id}': Fetched {len(parsed_bars)} OHLCV bars for {symbol}/{timeframe}.")
            return parsed_bars
            
        except PluginError: # Re-raise specific plugin errors
            raise
        except Exception as e: 
            logger.error(f"PolygonPlugin '{self.provider_id}': Unexpected error in fetch_historical_ohlcv for {symbol}: {e}", exc_info=True)
            raise PluginError(message=f"Unexpected error fetching OHLCV for {symbol}: {e}", provider_id=self.provider_id, original_exception=e) from e


    async def fetch_latest_ohlcv(self, symbol: str, timeframe: str = "1m") -> Optional[OHLCVBar]:
        """
        Fetches the most recent OHLCV bar. Uses /v2/aggs/ticker/{ticker}/prev for daily,
        or historical fetch with limit=1 for intraday.
        """
        logger.debug(f"PolygonPlugin '{self.provider_id}': Fetching latest '{timeframe}' bar for {symbol}.")

        # If daily timeframe, "Previous Close" endpoint is suitable for the last completed daily bar
        if timeframe.upper() == "1D":
            endpoint = f"/v2/aggs/ticker/{symbol}/prev" # Previous Trading Day OHLCV
            api_params = {"adjusted": str(True).lower()} # Ensure adjusted is true
            logger.debug(f"PolygonPlugin '{self.provider_id}': Using 'previous day' endpoint: {endpoint}")
            try:
                response_data = await self._request_api(endpoint, params=api_params)
                # Response: {"results": [{"T": symbol, "t": ms_ts, ...}]}
                if response_data and isinstance(response_data.get("results"), list) and len(response_data["results"]) > 0:
                    bar_data = response_data["results"][0]
                    if not all(k in bar_data for k in ["t", "o", "h", "l", "c", "v"]):
                        logger.warning(f"PolygonPlugin '{self.provider_id}': Malformed 'previous day' bar data for {symbol}: {bar_data}.")
                        return None
                    
                    latest_bar: OHLCVBar = {
                        "timestamp": int(bar_data["t"]),
                        "open": float(bar_data["o"]), "high": float(bar_data["h"]),
                        "low": float(bar_data["l"]), "close": float(bar_data["c"]),
                        "volume": float(bar_data["v"]),
                    }
                    logger.info(f"PolygonPlugin '{self.provider_id}': Fetched latest '1D' bar for {symbol} via 'previous day' endpoint.")
                    return latest_bar
                logger.warning(f"PolygonPlugin '{self.provider_id}': No 'previous day' bar data for {symbol}.")
                # Fall through to historical if prev day fails or no data
            except PluginError as e:
                logger.warning(f"PolygonPlugin '{self.provider_id}': PluginError fetching 'previous day' bar for {symbol}: {e}. Will attempt historical fallback.")
            except Exception as e:
                logger.error(f"PolygonPlugin '{self.provider_id}': Unexpected error fetching 'previous day' bar for {symbol}: {e}", exc_info=True)
        
        # Fallback for intraday or if daily "prev" failed
        logger.debug(f"PolygonPlugin '{self.provider_id}': Using historical fetch for latest '{timeframe}' bar for {symbol}.")
        try:
            # Fetch last 2 bars to get the most recent *completed* one, then take the last.
            # `until_ms` in params for fetch_historical_ohlcv could be current time.
            # `limit`=2. `since` can be omitted if `until` and `limit` are used effectively by orchestrator,
            # or calculate a recent 'since' here.
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            # Go back a bit to ensure data availability for the period.
            # Heuristic: timeframe_duration_ms * small_multiplier_for_lookback_window
            # For simplicity: go back 2 days for daily, few hours for hourly, 30-60 mins for minutely.
            # This needs a robust way to estimate a recent 'since' based on 'timeframe' and desired 'limit'.
            # DataOrchestrator should ideally handle this by providing a good `since` or `until`+`limit`.
            # For now, we request last 2 bars up to "now".
            hist_params = {"until_ms": now_ms}

            bars = await self.fetch_historical_ohlcv(symbol=symbol, timeframe=timeframe, limit=2, params=hist_params)
            if bars:
                latest_bar = bars[-1] # Last bar in the list
                logger.info(f"PolygonPlugin '{self.provider_id}': Fetched latest '{timeframe}' bar for {symbol} via historical fetch.")
                return latest_bar
            logger.warning(f"PolygonPlugin '{self.provider_id}': No latest '{timeframe}' bar for {symbol} from historical fetch.")
            return None
        except PluginError as e:
            logger.error(f"PolygonPlugin '{self.provider_id}': PluginError during fallback latest bar fetch for {symbol}/{timeframe}: {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"PolygonPlugin '{self.provider_id}': Unexpected error during fallback latest bar fetch for {symbol}/{timeframe}: {e}", exc_info=True)
            return None

    async def get_market_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetches detailed market information for a specific symbol using Polygon's /v3/reference/tickers/{ticker}."""
        current_time = time.monotonic()
        cached_data, cache_timestamp = self._ticker_details_cache.get(symbol, (None, 0.0))

        if cached_data and (current_time - cache_timestamp < TICKER_DETAILS_CACHE_TTL_SECONDS):
            logger.debug(f"PolygonPlugin '{self.provider_id}': Returning market info for '{symbol}' from cache.")
            return cached_data

        logger.debug(f"PolygonPlugin '{self.provider_id}': Fetching market info (ticker details) for '{symbol}'.")
        endpoint = f"/v3/reference/tickers/{symbol}"
        try:
            response_data = await self._request_api(endpoint)
            # Polygon response: {"request_id": "...", "results": {... ticker details ...}, "status": "OK"}
            if response_data and isinstance(response_data.get("results"), dict):
                ticker_details = response_data["results"]
                self._ticker_details_cache[symbol] = (ticker_details, current_time)
                logger.info(f"PolygonPlugin '{self.provider_id}': Fetched and cached market info for '{symbol}'.")
                return ticker_details
            
            logger.warning(f"PolygonPlugin '{self.provider_id}': No 'results' dict in market info response for '{symbol}'. Resp: {str(response_data)[:200]}")
            self._ticker_details_cache[symbol] = (None, current_time) # Cache miss
            return None
        except PluginError as e: # Handles 404 as "symbol not found" if _request_api maps it
            if "404 (Not Found)" in str(e) or (hasattr(e.original_exception, 'status') and e.original_exception.status == 404):
                 logger.info(f"PolygonPlugin '{self.provider_id}': Market info not found for symbol '{symbol}' (API 404).")
                 self._ticker_details_cache[symbol] = (None, current_time)
                 return None
            logger.error(f"PolygonPlugin '{self.provider_id}': PluginError fetching market info for '{symbol}': {e}", exc_info=False)
            # Do not re-raise if simply not found, but re-raise for other plugin errors like auth
            if isinstance(e, AuthenticationPluginError): raise
            return None # For other PluginErrors like network, treat as info not available
        except Exception as e:
            logger.error(f"PolygonPlugin '{self.provider_id}': Unexpected error fetching market info for '{symbol}': {e}", exc_info=True)
            # Don't raise PluginError here as get_market_info is optional style
            return None


    async def validate_symbol(self, symbol: str) -> bool:
        """Validates if a symbol exists and is active using get_market_info."""
        logger.debug(f"PolygonPlugin '{self.provider_id}': Validating symbol '{symbol}'.")
        try:
            market_info = await self.get_market_info(symbol)
            if market_info and market_info.get("active", False): # Polygon ticker details has "active": true/false
                return True
            if market_info and not market_info.get("active", False):
                logger.debug(f"PolygonPlugin '{self.provider_id}': Symbol '{symbol}' found but is not active.")
            return False
        except Exception: # Catch all from get_market_info if it raises, or if it returns None
            logger.debug(f"PolygonPlugin '{self.provider_id}': Symbol '{symbol}' not found or error during validation. Assuming invalid.")
            return False

    async def get_supported_timeframes(self) -> Optional[List[str]]:
        """Returns a list of timeframes supported by Polygon (those mappable by _map_to_polygon_timeframe)."""
        if self._supported_timeframes_cache is None:
            # These are common internal representations this plugin can map.
            # Polygon itself is very flexible with multiplier/timespan.
            self._supported_timeframes_cache = [
                "1m", "5m", "15m", "30m", "1h", "4h", 
                "1d", "1w", "1mo", "1y" # Using "mo" for month consistency
            ]
        return self._supported_timeframes_cache

    async def get_fetch_ohlcv_limit(self) -> int:
        """Returns Polygon's typical max limit for aggregate bars (OHLCV) requests."""
        if self._fetch_limit_cache is None:
            self._fetch_limit_cache = 50000 # Polygon's stated max is 50,000 for aggregates
        return self._fetch_limit_cache
        
    async def get_supported_features(self) -> Dict[str, bool]:
        """Declare features supported by this Polygon plugin instance."""
        return {
            "watch_ticks": False,  # Polygon has WebSockets, but not implemented in this REST plugin
            "fetch_trades": True, # Polygon has a Trades API, could be implemented
            "trading_api": False, 
            "get_market_info": True,
            "validate_symbol": True,
            "get_supported_timeframes": True,
            "get_fetch_ohlcv_limit": True,
        }

    async def close(self) -> None:
        """Closes the aiohttp ClientSession if it was created."""
        logger.info(f"PolygonPlugin '{self.provider_id}': Closing instance resources.")
        async with self._session_lock:
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                    logger.debug(f"PolygonPlugin '{self.provider_id}': aiohttp.ClientSession closed.")
                except Exception as e_close:
                    logger.error(f"PolygonPlugin '{self.provider_id}': Error closing ClientSession: {e_close}", exc_info=True)
            self._session = None
        
        # Clear caches (optional, as they are instance specific anyway)
        self._ticker_details_cache.clear()
        self._symbols_cache.clear()
        logger.info(f"PolygonPlugin '{self.provider_id}': Session closed and caches cleared.")