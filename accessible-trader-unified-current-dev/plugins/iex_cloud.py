# plugins/iex_cloud.py

import asyncio
import logging
import os
import time
import random # For retry jitter
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo # For timezone conversions (requires Python 3.9+)
# If Python < 3.9, you might need `pytz` for timezone handling:
# import pytz

import aiohttp
from typing import Any, Dict, List, Optional, Tuple, List

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

IEX_CLOUD_BASE_URL_PROD = "https://cloud.iexapis.com/stable"
IEX_CLOUD_BASE_URL_SANDBOX = "https://sandbox.iexapis.com/stable"

# Default retry configuration
DEFAULT_IEX_RETRY_COUNT = 3
DEFAULT_IEX_RETRY_DELAY_BASE_S = 1.0

# Cache TTLs (in seconds)
SYMBOLS_CACHE_TTL_SECONDS = 6 * 3600  # 6 hours
MARKET_INFO_CACHE_TTL_SECONDS = 24 * 3600 # 24 hours

# IEX Cloud often uses US/Eastern for its market times
# For Python 3.9+
US_EASTERN_TZ = ZoneInfo("America/New_York")
# For Python < 3.9 with pytz:
# US_EASTERN_TZ = pytz.timezone("America/New_York")


class IEXCloudPlugin(MarketPlugin):
    plugin_key: str = "iexcloud"
    # Based on IEX Cloud's typical offerings.
    supported_markets: List[str] = ["us_equity", "crypto", "forex", "etf", "mutual_fund"] # Forex via /fx/latest or /fx/historical

    def __init__(
        self,
        provider_id: str, # Expected to be "iexcloud"
        api_key: Optional[str] = None, # This will be the IEX Cloud Secret Token
        api_secret: Optional[str] = None, # Not used by IEX Cloud directly
        api_passphrase: Optional[str] = None, # Not used
        is_testnet: bool = False, # Determines if sandbox URL is used
        request_timeout: int = 30000,
        verbose_logging: bool = False,
        retry_count: int = DEFAULT_IEX_RETRY_COUNT,
        retry_delay_base: float = DEFAULT_IEX_RETRY_DELAY_BASE_S,
        **kwargs: Any
    ):
        if provider_id.lower() != "iexcloud":
            raise PluginError(
                message=f"IEXCloudPlugin initialized with incorrect provider_id: '{provider_id}'. Expected 'iexcloud'.",
                provider_id=provider_id
            )

        # IEX Cloud uses one token, typically referred to as 'api_key' in our system
        resolved_api_key = api_key or os.getenv("IEX_CLOUD_SECRET_TOKEN")

        super().__init__(
            provider_id="iexcloud",
            api_key=resolved_api_key, # Store the secret token here
            api_secret=None,
            api_passphrase=None,
            is_testnet=is_testnet,
            request_timeout=request_timeout,
            verbose_logging=verbose_logging,
            **kwargs
        )

        self._base_url = IEX_CLOUD_BASE_URL_SANDBOX if self.is_testnet else IEX_CLOUD_BASE_URL_PROD
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        
        self.retry_count = retry_count
        self.retry_delay_base = retry_delay_base

        self._symbols_cache: Dict[str, Tuple[Optional[List[str]], float]] = {} # market -> (symbols, timestamp)
        self._market_info_cache: Dict[str, Tuple[Optional[Dict[str, Any]], float]] = {} # symbol -> (info, timestamp)
        self._supported_timeframes_cache: Optional[List[str]] = None
        # IEX Cloud intraday limit is often per day; daily chart data varies by range.
        # For intraday-prices, it's typically the full day's data if no specific time range is requested.
        self._fetch_limit_cache: Optional[int] = 390 # Approx number of minutes in a trading day for 1-min bars

        if not self.api_key:
            logger.warning(
                f"IEXCloudPlugin for '{self.provider_id}' initialized without an API Token (Secret Token). "
                "Operations will fail. Ensure IEX_CLOUD_SECRET_TOKEN is set or provided."
            )
        logger.info(
            f"IEXCloudPlugin instance initialized. Provider: '{self.provider_id}', "
            f"Environment: {'Sandbox' if self.is_testnet else 'Production'}, API Token Provided: {bool(self.api_key)}."
        )

    @classmethod
    def get_plugin_key(cls) -> str:
        return cls.plugin_key

    @classmethod
    def get_supported_markets(cls) -> List[str]:
        return cls.supported_markets

    @classmethod
    def list_configurable_providers(cls) -> List[str]:
        return ["iexcloud"]

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session is None or self._session.closed:
                timeout_seconds = self.request_timeout / 1000.0
                timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                self._session = aiohttp.ClientSession(timeout=timeout)
                logger.debug(f"IEXCloudPlugin '{self.provider_id}': New aiohttp.ClientSession created.")
            return self._session

    async def _request_api(
        self,
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET"
    ) -> Any:
        if not self.api_key:
            raise AuthenticationPluginError(provider_id=self.provider_id, message="IEX Cloud API Token is required.")

        session = await self._get_session()
        url = f"{self._base_url}{endpoint}"
        
        request_params = params.copy() if params else {}
        request_params["token"] = self.api_key

        response_text_snippet = ""
        last_exception: Optional[Exception] = None

        for attempt in range(self.retry_count + 1):
            try:
                if self.verbose_logging:
                    logger.debug(f"IEXCloudPlugin '{self.provider_id}': Requesting {method} {url}, Params: {request_params} (Attempt {attempt+1})")

                async with session.request(method, url, params=request_params) as response:
                    response_text = await response.text() # Read text first for better error context
                    response_text_snippet = response_text[:500]

                    if self.verbose_logging:
                        logger.debug(f"IEXCloudPlugin '{self.provider_id}': Response Status {response.status} from {url}. Body: {response_text_snippet}")
                    
                    if response.status == 401 or response.status == 403: # Forbidden / Unauthorized
                        raise AuthenticationPluginError(provider_id=self.provider_id, message=f"IEX Cloud API Error {response.status}: {response_text_snippet}")
                    if response.status == 402: # Payment Required (often quota exceeded)
                         raise NetworkPluginError(provider_id=self.provider_id, message=f"IEX Cloud API Error 402 (Payment/Quota): {response_text_snippet}")
                    if response.status == 429: # Too Many Requests
                        raise NetworkPluginError(provider_id=self.provider_id, message=f"IEX Cloud API Error 429 (Rate Limit): {response_text_snippet}")

                    # IEX Cloud errors are often plain text, not JSON, but check content type
                    if response.status >= 400 and response.content_type != 'application/json':
                        # If it's an error and not JSON, raise_for_status will use the text
                        response.raise_for_status() 
                    
                    # If it might be JSON, try to parse for more detailed error messages
                    if response.content_type == 'application/json':
                        try:
                            parsed_json = await response.json() # Use Quart's internal method if available or aiohttp's
                            if isinstance(parsed_json, dict) and "message" in parsed_json and response.status >=400: # Check if it's an error structure
                                error_message = parsed_json["message"]
                                logger.error(f"IEXCloudPlugin '{self.provider_id}': API returned JSON error for {url}. Message: {error_message}")
                                # Re-check specific codes if the JSON provides more context
                                if response.status == 401 or response.status == 403: raise AuthenticationPluginError(provider_id=self.provider_id, message=f"IEX Cloud API Error {response.status}: {error_message}")
                                if response.status == 402: raise NetworkPluginError(provider_id=self.provider_id, message=f"IEX Cloud API Error 402 (Payment/Quota): {error_message}")

                                raise PluginError(message=f"IEX Cloud API Error {response.status}: {error_message}", provider_id=self.provider_id)
                            elif response.status >=400: # JSON but not the expected error structure
                                response.raise_for_status() # Let aiohttp handle it
                            # If no error, return the parsed JSON
                            return parsed_json

                        except Exception as json_ex: # Includes JSONDecodeError
                            if response.status >= 400: # If parsing JSON failed on an error response
                                logger.warning(f"IEXCloudPlugin '{self.provider_id}': Failed to parse JSON error response for {url}. Status: {response.status}. Text: {response_text_snippet}. Error: {json_ex}")
                                response.raise_for_status() # Fallback to raising based on status code
                            # If it was a successful response but not JSON, handle below
                            pass # Fall through if parsing fails for non-error or non-JSON

                    # If not JSON or parsing failed for a successful response, handle based on text
                    if response.status == 204: return {} # No content
                    
                    # If we are here, it means the response was successful but may not have been parsed as JSON yet.
                    # If it's expected to be JSON and wasn't parsed, try now. Otherwise, it might be plain text (unlikely for data APIs).
                    try:
                        return await response.json(content_type=None) # Try to parse as JSON
                    except Exception: # If it's truly not JSON even on success
                        logger.warning(f"IEXCloudPlugin '{self.provider_id}': Response from {url} was successful but not valid JSON. Text: {response_text_snippet}")
                        return response_text # Return raw text as a last resort for successful non-JSON

            except (NetworkPluginError, aiohttp.ClientConnectionError, aiohttp.ServerDisconnectedError, asyncio.TimeoutError) as e:
                last_exception = e
                if attempt == self.retry_count:
                    logger.error(f"IEXCloudPlugin '{self.provider_id}': Max retries for {url}. Error: {e}", exc_info=False)
                    raise NetworkPluginError(self.provider_id, f"API call to {url} failed: {e}", e) from e
                delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.5)
                logger.warning(f"IEXCloudPlugin ('{self.provider_id}'): {type(e).__name__} for {url} (Attempt {attempt+1}). Retrying in {delay:.2f}s.")
                await asyncio.sleep(delay)
            except AuthenticationPluginError: raise
            except PluginError: raise
            except aiohttp.ClientResponseError as e:
                logger.error(f"IEXCloudPlugin '{self.provider_id}': HTTP error {e.status} for {url}: {e.message}. Resp: {response_text_snippet}", exc_info=False)
                if e.status >= 500 and attempt < self.retry_count: # Retry server errors
                    last_exception = e
                    delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.5)
                    logger.warning(f"IEXCloudPlugin ('{self.provider_id}'): HTTP {e.status} (Attempt {attempt+1}). Retrying in {delay:.2f}s.")
                    await asyncio.sleep(delay)
                    continue
                raise PluginError(f"HTTP error {e.status}: {e.message}", self.provider_id, e) from e
            except Exception as e:
                logger.error(f"IEXCloudPlugin '{self.provider_id}': Unexpected error for {url}: {e}. Resp: {response_text_snippet}", exc_info=True)
                last_exception = e
                if attempt == self.retry_count:
                    raise PluginError(f"Unexpected API error: {e}", self.provider_id, e) from e
                delay = self.retry_delay_base * (2 ** attempt)
                await asyncio.sleep(delay)
        
        if last_exception:
            raise PluginError(f"API call failed for {url}. Last: {last_exception}", self.provider_id, last_exception)
        raise PluginError(f"API call failed unexpectedly for {url}", self.provider_id)

    def _parse_iex_timestamp(self, date_val: str, minute_val: Optional[str] = None) -> int:
        """
        Parses IEX Cloud's date and optional minute string into a UTC millisecond timestamp.
        IEX Cloud intraday timestamps are typically US/Eastern. Daily are just dates.
        """
        if minute_val: # Intraday data
            try:
                # Combine date and minute, assume date_val is YYYY-MM-DD for intraday context
                dt_naive = datetime.strptime(f"{date_val} {minute_val}", "%Y-%m-%d %H:%M")
                dt_eastern = US_EASTERN_TZ.localize(dt_naive)
                dt_utc = dt_eastern.astimezone(timezone.utc)
                return int(dt_utc.timestamp() * 1000)
            except Exception as e:
                logger.error(f"IEXCloudPlugin: Error parsing intraday timestamp {date_val} {minute_val}: {e}")
                # Fallback or error
                return 0 # Or raise
        else: # Daily data
            try:
                dt_naive = datetime.strptime(date_val, "%Y-%m-%d")
                # For daily bars, the timestamp usually represents market open or EOD.
                # To be consistent, let's assume it's the start of the day in US/Eastern, then convert to UTC.
                # Or, treat as UTC directly if IEX implies EOD UTC for daily data.
                # Let's assume the date represents the market day, timestamped at market open (e.g. 9:30 ET -> UTC)
                # For simplicity, we can also just take it as UTC midnight if precise market open isn't critical for daily.
                # Let's assume it's UTC midnight for the given date for daily bars.
                dt_utc = datetime(dt_naive.year, dt_naive.month, dt_naive.day, tzinfo=timezone.utc)
                return int(dt_utc.timestamp() * 1000)
            except Exception as e:
                logger.error(f"IEXCloudPlugin: Error parsing daily timestamp {date_val}: {e}")
                return 0 # Or raise

    def _map_internal_timeframe_to_iex_params(self, internal_timeframe: str, symbol: str, since_ms: Optional[int], until_ms: Optional[int]) -> Tuple[str, Dict[str, Any]]:
        """
        Maps internal timeframe to IEX Cloud endpoint and parameters.
        Returns (endpoint, api_params_dict).
        """
        tf_lower = internal_timeframe.lower()
        api_params = {}
        
        # Intraday minute data
        # e.g., "1m", "5m", "15m", "30m", "1h" (map to 60m if not directly supported as '1h')
        if tf_lower.endswith('m') or tf_lower.endswith('min'):
            try:
                interval_val = int(tf_lower.rstrip('min')) # Works for "1m", "5min", etc.
                if interval_val <= 0: raise ValueError("Minute interval must be positive")
                endpoint = f"/stock/{symbol}/intraday-prices"
                api_params["chartInterval"] = interval_val
                # For intraday, IEX often uses specific dates.
                # If since_ms is given, find the date for it. If multiple days, may need multiple calls or use chartByDay.
                # IEX `intraday-prices` can take `exactDate=YYYYMMDD` or fetches latest if no date.
                # If `since_ms` and `until_ms` span multiple days for intraday, this becomes complex.
                # For simplicity, if `since_ms` is provided, we use its date for `exactDate`.
                # This means multi-day intraday fetches would need paging by day in orchestrator.
                if since_ms:
                     api_params["exactDate"] = datetime.fromtimestamp(since_ms / 1000.0, tz=US_EASTERN_TZ).strftime("%Y%m%d")
                # `until_ms` is not directly used by /intraday-prices in this way; filtering happens post-fetch.
                return endpoint, api_params
            except ValueError:
                pass # Fall through if not a simple minute format
        
        if tf_lower == "1h": # map 1h to 60min for intraday-prices
            endpoint = f"/stock/{symbol}/intraday-prices"
            api_params["chartInterval"] = 60
            if since_ms:
                api_params["exactDate"] = datetime.fromtimestamp(since_ms / 1000.0, tz=US_EASTERN_TZ).strftime("%Y%m%d")
            return endpoint, api_params

        # Daily, Weekly, Monthly data using /chart endpoint
        endpoint = f"/stock/{symbol}/chart"
        # IEX /chart ranges: 5d, 1mm (1 month using 'mm'), 3mm, 6mm, ytd, 1y, 2y, 5y, max, date/YYYYMMDD, dynamic
        # We need to map our generic since/until/limit to these ranges, or use date ranges.
        # Using specific date range is often better for precision.
        # `/stock/{symbol}/chart/date/YYYYMMDD` or `/stock/{symbol}/chart/date/YYYYMMDD?chartByDay=true`
        # The `/chart/{range}` with `range` like `1y` is simpler if broad history is needed.
        # If `since_ms` is provided, we might use a range that covers it.
        # For now, let's default to a common range if specific mapping is hard.
        
        if since_ms:
            # Calculate a range based on since_ms.
            # This is a simplification. A robust solution would pick the best IEX range string.
            days_diff = (datetime.now(timezone.utc) - datetime.fromtimestamp(since_ms / 1000.0, tz=timezone.utc)).days
            if days_diff <= 5: api_params["range"] = "5d" # Might give intraday for 5d, not daily. Check IEX docs.
            elif days_diff <= 30: api_params["range"] = "1mm"
            elif days_diff <= 90: api_params["range"] = "3mm"
            elif days_diff <= 180: api_params["range"] = "6mm"
            elif days_diff <= 365: api_params["range"] = "1y"
            elif days_diff <= 365*2: api_params["range"] = "2y"
            else: api_params["range"] = "max"
        else: # Default if no since_ms (e.g., for latest daily)
             api_params["range"] = "1mm" # Fetch 1 month of daily data

        if tf_lower == '1d' or tf_lower == 'd': # Daily is default for /chart ranges
            pass
        elif tf_lower == '1w' or tf_lower == 'w':
            api_params["chartByDay"] = "true" # Fetch daily, then resample to weekly
            logger.info("IEXCloudPlugin: Fetching daily data for weekly resampling (chartByDay=true).")
        elif tf_lower == '1mo' or tf_lower == 'mon':
            api_params["chartByDay"] = "true" # Fetch daily, then resample to monthly
            logger.info("IEXCloudPlugin: Fetching daily data for monthly resampling (chartByDay=true).")
        else:
            logger.warning(f"IEXCloudPlugin: Timeframe '{internal_timeframe}' not directly mappable to IEX /chart. Using default range and daily data.")
        
        # `until_ms` is not directly used by /chart/{range}; filtering happens post-fetch.
        return f"{endpoint}/{api_params.pop('range', '1mm')}", api_params


    async def get_symbols(self, market: str) -> List[str]:
        normalized_market = market.lower()
        current_time = time.monotonic()
        
        cached_data, cache_timestamp = self._symbols_cache.get(normalized_market, (None, 0.0))
        if cached_data and (current_time - cache_timestamp < SYMBOLS_CACHE_TTL_SECONDS):
            logger.debug(f"IEXCloudPlugin: Returning symbols for '{normalized_market}' from cache.")
            return cached_data

        endpoint = ""
        if normalized_market in ["us_equity", "global_equity", "etf", "mutual_fund"]:
            endpoint = "/ref-data/symbols" # General list, includes various types
            # Could also use /ref-data/exchange/{exchange}/symbols for more specificity
        elif normalized_market == "crypto":
            endpoint = "/ref-data/crypto/symbols"
        # Forex symbols from IEX are often specific pairs, not a full list endpoint in the same way.
        # They are usually known, e.g., "USDJPY".
        elif normalized_market == "forex":
            logger.warning("IEXCloudPlugin: Forex symbol list not typically fetched via a dedicated endpoint. Returning common pairs. Implement specific logic if needed.")
            # Example common pairs, this should be more dynamic or configured
            common_forex = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
            self._symbols_cache[normalized_market] = (common_forex, current_time)
            return common_forex
        else:
            raise PluginError(f"Unsupported market '{market}' for IEX Cloud symbol listing.", self.provider_id)

        logger.debug(f"IEXCloudPlugin: Fetching symbols for '{normalized_market}' from '{endpoint}'.")
        
        try:
            response_data = await self._request_api(endpoint) # No extra params needed typically
            symbols_list: List[str] = []
            if isinstance(response_data, list):
                for item in response_data:
                    if isinstance(item, dict) and "symbol" in item and item.get("isEnabled", True):
                        # IEX ref-data can have 'type' (ad - ADR, cs - Common Stock, et - ETF, etc.)
                        # Filter here if needed based on normalized_market
                        item_type = item.get("type", "").lower()
                        if normalized_market == "us_equity" and item_type not in ['cs', 'ad', 'et']: # Example filter
                            # pass # Or be more specific if 'global_equity' is different
                            symbols_list.append(item["symbol"]) # For now, add if enabled
                        elif normalized_market == "etf" and item_type == 'et':
                             symbols_list.append(item["symbol"])
                        elif normalized_market == "mutual_fund" and item_type == 'mf': # Check IEX type for mutual funds
                             symbols_list.append(item["symbol"])
                        elif normalized_market == "crypto": # crypto endpoint has different structure
                            symbols_list.append(item["symbol"])
                        elif normalized_market == "global_equity": # Catch-all for enabled stocks
                             symbols_list.append(item["symbol"])


            self._symbols_cache[normalized_market] = (symbols_list, current_time)
            logger.info(f"IEXCloudPlugin: Fetched {len(symbols_list)} symbols for '{normalized_market}'.")
            return sorted(list(set(symbols_list)))
        except PluginError as e:
            logger.error(f"IEXCloudPlugin: PluginError fetching symbols for '{market}': {e}", exc_info=False)
            if cached_data: return cached_data
            raise
        except Exception as e:
            logger.error(f"IEXCloudPlugin: Unexpected error fetching symbols for '{market}': {e}", exc_info=True)
            if cached_data: return cached_data
            raise PluginError(f"Unexpected error fetching symbols: {e}", self.provider_id, e) from e


    async def fetch_historical_ohlcv(
        self, symbol: str, timeframe: str,
        since: Optional[int] = None, limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None # For passthrough like exactDate
    ) -> List[OHLCVBar]:
        
        endpoint, api_params_mapped = self._map_internal_timeframe_to_iex_params(timeframe, symbol, since, params.get("until_ms") if params else None)
        if params: api_params_mapped.update(params) # Merge mapped params with direct passthrough

        # IEX Cloud limit for /chart is by range; for /intraday-prices, it's usually full day or specified by exactDate.
        # The `limit` parameter to this function will be applied post-fetch.

        logger.debug(f"IEXCloudPlugin: Fetching OHLCV for {symbol} @ {timeframe}. Endpoint: {endpoint}, API Params: {api_params_mapped}")

        try:
            response_data = await self._request_api(endpoint, params=api_params_mapped)
            parsed_bars: List[OHLCVBar] = []

            if isinstance(response_data, list):
                for bar_data in response_data:
                    if not isinstance(bar_data, dict): continue
                    try:
                        # Determine keys for timestamp based on endpoint used (daily vs intraday)
                        date_key = bar_data.get("date") or bar_data.get("priceDate") # for /chart, /stock/{symbol}/historical-prices
                        minute_key = bar_data.get("minute") # for /intraday-prices, /chart with minute precision

                        if not date_key: # If no date field, cannot parse
                            logger.warning(f"IEXCloudPlugin: Missing 'date' or 'priceDate' field in bar: {bar_data}")
                            continue
                        
                        ts_ms = self._parse_iex_timestamp(date_key, minute_key)
                        if ts_ms == 0: continue # Skip if parsing failed

                        # Handle potential None values for OHLCV from IEX (especially intraday if market closed)
                        open_val = bar_data.get("open", bar_data.get("marketOpen"))
                        high_val = bar_data.get("high", bar_data.get("marketHigh"))
                        low_val = bar_data.get("low", bar_data.get("marketLow"))
                        close_val = bar_data.get("close", bar_data.get("marketClose"))
                        volume_val = bar_data.get("volume", bar_data.get("marketVolume"))

                        # If any OHLC is None, this bar might be incomplete (e.g. pre-market data point without a trade)
                        # Skip if essential OHLC are missing. Close might be None if it's the current incomplete bar.
                        if open_val is None or high_val is None or low_val is None: # Close can sometimes be null for current bar
                            # For IEX intraday, null OHLC often means no trades in that minute.
                            # We should decide if we want to represent these as "gaps" or impute.
                            # For now, let's skip them if they are truly null (not 0).
                            # A "volume" of 0 but present OHLC is fine.
                            if endpoint.endswith("intraday-prices") and volume_val == 0 and open_val is None: # Common for no-trade minutes
                                 logger.debug(f"IEXCloudPlugin: Skipping no-trade minute for {symbol}: {bar_data}")
                                 continue

                        parsed_bars.append({
                            "timestamp": ts_ms,
                            "open": float(open_val) if open_val is not None else 0.0, # Decide fallback for None
                            "high": float(high_val) if high_val is not None else 0.0,
                            "low": float(low_val) if low_val is not None else 0.0,
                            "close": float(close_val) if close_val is not None else (open_val if open_val is not None else 0.0), # Use open if close is None
                            "volume": float(volume_val) if volume_val is not None else 0.0,
                        })
                    except (TypeError, ValueError, KeyError) as e_parse:
                        logger.warning(f"IEXCloudPlugin: Error parsing bar for {symbol}: {bar_data}. Error: {e_parse}. Skipping.", exc_info=False)
            
            # Data from IEX is typically oldest first. If not, sort here.
            parsed_bars.sort(key=lambda b: b['timestamp'])
            
            # Final limit application happens in DataOrchestrator._apply_filters
            logger.info(f"IEXCloudPlugin: Fetched {len(parsed_bars)} OHLCV bars for {symbol}/{timeframe}.")
            return parsed_bars
        except PluginError as e:
             if "unknown symbol" in str(e).lower() or \
               (isinstance(e.original_exception, aiohttp.ClientResponseError) and e.original_exception.status == 404):
                logger.info(f"IEXCloudPlugin: Symbol '{symbol}' not found by API for OHLCV. Params: {api_params_mapped}")
                return []
             raise
        except Exception as e:
            logger.error(f"IEXCloudPlugin: Unexpected error fetching OHLCV for {symbol}: {e}", exc_info=True)
            raise PluginError(f"Unexpected error fetching OHLCV for {symbol}: {e}", self.provider_id, e) from e


    async def fetch_latest_ohlcv(self, symbol: str, timeframe: str = "1m") -> Optional[OHLCVBar]:
        logger.debug(f"IEXCloudPlugin: Fetching latest '{timeframe}' bar for {symbol}.")
        try:
            # Option 1: Use /quote endpoint (good for daily summary or latest trade)
            if timeframe == '1d': # /quote is most relevant for "latest daily"
                quote_data = await self._request_api(f"/stock/{symbol}/quote")
                if isinstance(quote_data, dict) and all(k in quote_data for k in ["latestPrice", "previousClose"]):
                    # Construct a daily bar from quote. Timestamp needs careful handling.
                    # 'latestUpdate' is epoch ms UTC for latestPrice, 'iexLastUpdated' for IEX-sourced data
                    ts_ms = quote_data.get("latestUpdate") or quote_data.get("iexLastUpdated") or int(time.time() * 1000)
                    # Ensure it's a daily timestamp (e.g., market close or EOD UTC)
                    # For simplicity, use the date of the latest price.
                    dt_utc = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                    daily_ts_ms = int(datetime(dt_utc.year, dt_utc.month, dt_utc.day, tzinfo=timezone.utc).timestamp() * 1000)

                    return { # Note: This is an approximation of a daily bar from a quote
                        "timestamp": daily_ts_ms,
                        "open": float(quote_data.get("iexOpen", quote_data.get("previousClose"))), # iexOpen if available for current day, else previousClose
                        "high": float(quote_data.get("high", quote_data.get("latestPrice"))), # 'high' might be day high or null
                        "low": float(quote_data.get("low", quote_data.get("latestPrice"))),   # 'low' might be day low or null
                        "close": float(quote_data["latestPrice"]),
                        "volume": float(quote_data.get("volume", quote_data.get("latestVolume", 0.0))),
                    }

            # Option 2: For intraday, fetch a recent intraday bar
            # Use fetch_historical_ohlcv to get the last few bars and take the most recent
            # Look back a short period to ensure we get data
            since_lookback = int((datetime.now(timezone.utc) - timedelta(hours=4)).timestamp() * 1000) if 'm' in timeframe or 'h' in timeframe else \
                             int((datetime.now(timezone.utc) - timedelta(days=5)).timestamp() * 1000)


            bars = await self.fetch_historical_ohlcv(symbol, timeframe, since=since_lookback, limit=5) # Fetch a few recent bars
            if bars:
                latest_bar = bars[-1] # Already sorted oldest first
                logger.info(f"IEXCloudPlugin: Fetched latest '{timeframe}' bar for {symbol} @ {format_timestamp_to_iso(latest_bar['timestamp'])} via historical.")
                return latest_bar
                
            logger.warning(f"IEXCloudPlugin: No latest '{timeframe}' bar found for {symbol}.")
            return None

        except PluginError as e:
            logger.error(f"IEXCloudPlugin: PluginError fetching latest bar for {symbol}/{timeframe}: {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"IEXCloudPlugin: Unexpected error fetching latest bar for {symbol}/{timeframe}: {e}", exc_info=True)
            return None

    async def get_market_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        # (Similar to FMP or TwelveData implementation, using /stock/{symbol}/company)
        current_time = time.monotonic()
        cached_data, cache_timestamp = self._market_info_cache.get(symbol, (None, 0.0))

        if cached_data and (current_time - cache_timestamp < MARKET_INFO_CACHE_TTL_SECONDS):
            return cached_data
        
        # For Forex (/fx/latest?symbols=EURUSD) or Crypto (/crypto/{symbol}/price) info might be different
        # This primarily targets stocks.
        endpoint = f"/stock/{symbol}/company"
        logger.debug(f"IEXCloudPlugin: Fetching market info (company) for '{symbol}'.")
        try:
            response_data = await self._request_api(endpoint) # Returns a direct dict
            if isinstance(response_data, dict) and "symbol" in response_data:
                self._market_info_cache[symbol] = (response_data, current_time)
                logger.info(f"IEXCloudPlugin: Fetched and cached company info for '{symbol}'.")
                return response_data
            
            logger.warning(f"IEXCloudPlugin: No valid company info in response for '{symbol}'. Resp: {str(response_data)[:200]}")
            self._market_info_cache[symbol] = (None, current_time)
            return None
        except PluginError as e:
            if "unknown symbol" in str(e).lower() or \
               (isinstance(e.original_exception, aiohttp.ClientResponseError) and e.original_exception.status == 404):
                logger.info(f"IEXCloudPlugin: Company info not found for symbol '{symbol}' (API 404).")
                self._market_info_cache[symbol] = (None, current_time)
                return None
            logger.error(f"IEXCloudPlugin: PluginError fetching company info for '{symbol}': {e}", exc_info=False)
            if isinstance(e, AuthenticationPluginError): raise
            return None
        except Exception as e:
            logger.error(f"IEXCloudPlugin: Unexpected error fetching company info for '{symbol}': {e}", exc_info=True)
            return None

    async def validate_symbol(self, symbol: str) -> bool:
        logger.debug(f"IEXCloudPlugin: Validating symbol '{symbol}'.")
        try:
            # Fetching quote is a lightweight way to check if symbol exists
            quote_data = await self._request_api(f"/stock/{symbol}/quote")
            return isinstance(quote_data, dict) and quote_data.get("symbol", "").upper() == symbol.upper()
        except Exception: # Catches PluginError (like 404 Unknown symbol) or other issues
            logger.debug(f"IEXCloudPlugin: Symbol '{symbol}' failed validation (e.g. quote fetch failed). Assuming invalid.")
            return False

    async def get_supported_timeframes(self) -> Optional[List[str]]:
        if self._supported_timeframes_cache is None:
            # Based on /intraday-prices (chartInterval) and /chart (ranges mapping to daily/weekly/monthly)
            # These are your *internal* representations that you can map.
            self._supported_timeframes_cache = [
                "1m", "5m", "10m", "15m", "30m", "1h", # Mapped to intraday chartInterval
                "1d", # Mapped to daily chart ranges
                "1w", # Requires daily -> weekly resampling
                "1mo" # Requires daily -> monthly resampling
            ]
        return self._supported_timeframes_cache

    async def get_fetch_ohlcv_limit(self) -> int:
        # For IEX /intraday-prices, you usually get data for a whole day or specified part.
        # For /chart, it's range-dependent.
        # This limit is more conceptual for how your DataOrchestrator might page.
        return self._fetch_limit_cache or 390 # e.g., 390 for 1-min bars in a trading day

    async def get_supported_features(self) -> Dict[str, bool]:
        return {
            "watch_ticks": False, # IEX Cloud has SSE streaming, not implemented here as simple REST
            "fetch_trades": True, # IEX has /trades, /last, etc. (not implemented in this draft)
            "trading_api": False, 
            "get_market_info": True, # Via /company
            "validate_symbol": True, # Via /quote
            "get_supported_timeframes": True,
            "get_fetch_ohlcv_limit": True,
        }

    async def close(self) -> None:
        logger.info(f"IEXCloudPlugin '{self.provider_id}': Closing instance resources.")
        async with self._session_lock:
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                    logger.debug(f"IEXCloudPlugin '{self.provider_id}': aiohttp.ClientSession closed.")
                except Exception as e_close:
                    logger.error(f"IEXCloudPlugin '{self.provider_id}': Error closing ClientSession: {e_close}", exc_info=True)
            self._session = None
        
        self._symbols_cache.clear()
        self._market_info_cache.clear()
        logger.info(f"IEXCloudPlugin '{self.provider_id}': Session closed and caches cleared.")