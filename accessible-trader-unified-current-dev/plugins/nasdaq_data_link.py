# plugins/nasdaq_data_link.py

import asyncio
import logging
import os
import time
import random # For retry jitter
from datetime import datetime, timezone
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

NASDAQ_DATA_LINK_BASE_URL = "https://data.nasdaq.com/api/v3"

DEFAULT_NDL_RETRY_COUNT = 3
DEFAULT_NDL_RETRY_DELAY_BASE_S = 2.0 # Their API can be strict on rate limits

# Cache TTLs
DATASET_METADATA_CACHE_TTL_SECONDS = 24 * 3600 # 24 hours

# Define known column name variations for OHLCV + Date
# Order implies preference if multiple matches (e.g., "Settle" often preferred over "Close" for futures)
DATE_COLUMN_CANDIDATES = ["Date", "Trade Date", "Trading Day"]
OPEN_COLUMN_CANDIDATES = ["Open", "First"]
HIGH_COLUMN_CANDIDATES = ["High", "Day High"]
LOW_COLUMN_CANDIDATES = ["Low", "Day Low"]
CLOSE_COLUMN_CANDIDATES = ["Settle", "Close", "Last", "Previous Settle"]
VOLUME_COLUMN_CANDIDATES = ["Volume", "Total Volume", "Trade Volume"]


class NasdaqDataLinkPlugin(MarketPlugin):
    plugin_key: str = "nasdaq_data_link" # Or "quandl" if you prefer
    # "Markets" are abstract here, representing categories of Quandl datasets
    supported_markets: List[str] = ["commodity_futures", "economic_data", "selected_stocks"] # Examples

    def __init__(
        self,
        provider_id: str, # Expected to be "nasdaqdatalink" or "quandl"
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None, # Not used
        api_passphrase: Optional[str] = None, # Not used
        is_testnet: bool = False, # NDL doesn't have a testnet concept
        request_timeout: int = 30000,
        verbose_logging: bool = False,
        retry_count: int = DEFAULT_NDL_RETRY_COUNT,
        retry_delay_base: float = DEFAULT_NDL_RETRY_DELAY_BASE_S,
        **kwargs: Any
    ):
        # Provider ID for this plugin instance will always be its own key
        super().__init__(
            provider_id=self.plugin_key, # Use plugin_key as the provider_id for this plugin
            api_key=api_key or os.getenv("NASDAQ_DATA_LINK_API_KEY") or os.getenv("QUANDL_API_KEY"),
            api_secret=None,
            api_passphrase=None,
            is_testnet=is_testnet, # Stored but not used by NDL API
            request_timeout=request_timeout,
            verbose_logging=verbose_logging,
            **kwargs
        )

        self._base_url = NASDAQ_DATA_LINK_BASE_URL
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        
        self.retry_count = retry_count
        self.retry_delay_base = retry_delay_base

        # Cache for dataset metadata: Key: quandl_code, Value: (metadata_dict, timestamp)
        self._dataset_metadata_cache: Dict[str, Tuple[Optional[Dict[str, Any]], float]] = {}
        self._supported_timeframes_cache: Optional[List[str]] = ["1d"] # Most NDL datasets are daily
        self._fetch_limit_cache: Optional[int] = None # NDL limit often generous per call, but overall usage metered

        if not self.api_key:
            logger.warning(
                f"{self.__class__.__name__} for '{self.provider_id}' initialized without an API Key. "
                "Operations will likely fail or be severely rate-limited. "
                "Ensure NASDAQ_DATA_LINK_API_KEY (or QUANDL_API_KEY) is set or provided."
            )
        logger.info(
            f"{self.__class__.__name__} instance initialized. Provider: '{self.provider_id}', API Key Provided: {bool(self.api_key)}."
        )

    @classmethod
    def get_plugin_key(cls) -> str:
        return cls.plugin_key

    @classmethod
    def get_supported_markets(cls) -> List[str]:
        return cls.supported_markets

    @classmethod
    def list_configurable_providers(cls) -> List[str]:
        """This plugin class handles only itself as a provider."""
        return [cls.plugin_key]

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session is None or self._session.closed:
                timeout_seconds = self.request_timeout / 1000.0
                timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                self._session = aiohttp.ClientSession(timeout=timeout)
                logger.debug(f"{self.__class__.__name__} '{self.provider_id}': New aiohttp.ClientSession created.")
            return self._session

    async def _request_api(
        self,
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET"
    ) -> Any:
        if not self.api_key:
            raise AuthenticationPluginError(provider_id=self.provider_id, message="Nasdaq Data Link API Key is required.")

        session = await self._get_session()
        url = f"{self._base_url}{endpoint}"
        
        request_params = params.copy() if params else {}
        request_params["api_key"] = self.api_key

        response_text_snippet = ""
        last_exception: Optional[Exception] = None

        for attempt in range(self.retry_count + 1):
            try:
                if self.verbose_logging:
                    logger.debug(f"{self.__class__.__name__} '{self.provider_id}': Requesting {method} {url}, Params: {request_params} (Attempt {attempt+1})")

                async with session.request(method, url, params=request_params) as response:
                    # NDL often returns JSON, but let's get text for robust error checking
                    response_text = await response.text()
                    response_text_snippet = response_text[:500]

                    if self.verbose_logging:
                        logger.debug(f"{self.__class__.__name__} '{self.provider_id}': Response Status {response.status} from {url}. Body: {response_text_snippet}")
                    
                    # Try to parse as JSON to check for NDL's error structure first
                    parsed_json = None
                    if response.content_type == 'application/json':
                        try:
                            parsed_json = json.loads(response_text) # Using standard json.loads
                            if isinstance(parsed_json, dict) and "quandl_error" in parsed_json:
                                q_error = parsed_json["quandl_error"]
                                code = q_error.get("code", "UnknownCode")
                                message = q_error.get("message", response_text_snippet)
                                logger.error(f"{self.__class__.__name__} '{self.provider_id}': API error {code} for {url}. Message: {message}")
                                if code in ["QEAx01", "QEPx02", "QEPx04"]: # Authentication related
                                    raise AuthenticationPluginError(provider_id=self.provider_id, message=f"NDL API Error {code}: {message}")
                                if code == "QELx04": # Limit related
                                    raise NetworkPluginError(provider_id=self.provider_id, message=f"NDL API Error {code} (Limit Exceeded): {message}")
                                if code == "QECx02": # Invalid code
                                    raise PluginError(message=f"NDL API Error {code} (Invalid Dataset Code): {message}", provider_id=self.provider_id)
                                raise PluginError(message=f"NDL API Error {code}: {message}", provider_id=self.provider_id)
                        except json.JSONDecodeError:
                            # If it's not JSON, but an error status, handle below
                            if response.status >= 400:
                                logger.warning(f"{self.__class__.__name__} '{self.provider_id}': Non-JSON error response from {url}. Status: {response.status}. Text: {response_text_snippet}")
                                # Fall through to response.raise_for_status()
                        # If parsed_json is set and no "quandl_error", it's likely good data

                    # General HTTP status checks
                    if response.status == 401 or response.status == 403:
                        raise AuthenticationPluginError(provider_id=self.provider_id, message=f"HTTP Error {response.status}: {response_text_snippet}")
                    if response.status == 429: # Rate limit
                        raise NetworkPluginError(provider_id=self.provider_id, message=f"HTTP Error 429 (Rate Limit): {response_text_snippet}")
                    
                    response.raise_for_status() # For other 4xx/5xx errors
                    
                    if response.status == 204: return {}
                    
                    return parsed_json if parsed_json else json.loads(response_text) # Return parsed JSON if available and valid

            except (NetworkPluginError, aiohttp.ClientConnectionError, aiohttp.ServerDisconnectedError, asyncio.TimeoutError) as e:
                last_exception = e
                if attempt == self.retry_count:
                    logger.error(f"{self.__class__.__name__} '{self.provider_id}': Max retries for {url}. Error: {e}", exc_info=False)
                    raise NetworkPluginError(self.provider_id, f"API call to {url} failed: {e}", e) from e
                delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.5)
                logger.warning(f"{self.__class__.__name__} ('{self.provider_id}'): {type(e).__name__} for {url} (Attempt {attempt+1}). Retrying in {delay:.2f}s.")
                await asyncio.sleep(delay)
            except AuthenticationPluginError: raise
            except PluginError: raise
            except aiohttp.ClientResponseError as e:
                logger.error(f"{self.__class__.__name__} '{self.provider_id}': HTTP error {e.status} for {url}: {e.message}. Resp: {response_text_snippet}", exc_info=False)
                if e.status >= 500 and attempt < self.retry_count:
                    last_exception = e
                    delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.5)
                    logger.warning(f"{self.__class__.__name__} ('{self.provider_id}'): HTTP {e.status} (Attempt {attempt+1}). Retrying in {delay:.2f}s.")
                    await asyncio.sleep(delay)
                    continue
                raise PluginError(f"HTTP error {e.status}: {e.message}", self.provider_id, e) from e
            except Exception as e:
                logger.error(f"{self.__class__.__name__} '{self.provider_id}': Unexpected error for {url}: {e}. Resp: {response_text_snippet}", exc_info=True)
                last_exception = e
                if attempt == self.retry_count:
                    raise PluginError(f"Unexpected API error: {e}", self.provider_id, e) from e
                delay = self.retry_delay_base * (2 ** attempt)
                await asyncio.sleep(delay)
        
        if last_exception:
            raise PluginError(f"API call failed for {url}. Last: {last_exception}", self.provider_id, last_exception)
        raise PluginError(f"API call failed unexpectedly for {url}", self.provider_id)

    def _parse_ndl_timestamp(self, date_str: str) -> int:
        """Parses NDL's date string ("YYYY-MM-DD") into UTC millisecond timestamp (00:00 UTC)."""
        try:
            dt_naive = datetime.strptime(date_str, "%Y-%m-%d")
            dt_utc = datetime(dt_naive.year, dt_naive.month, dt_naive.day, tzinfo=timezone.utc)
            return int(dt_utc.timestamp() * 1000)
        except ValueError:
            logger.error(f"{self.__class__.__name__}: Could not parse date string '{date_str}'")
            raise # Re-raise to be caught by caller

    def _get_column_indices(self, column_names: List[str]) -> Dict[str, Optional[int]]:
        """Finds indices of standard OHLCV and Date columns."""
        indices = {
            "date": None, "open": None, "high": None,
            "low": None, "close": None, "volume": None
        }
        
        name_map = {
            "date": DATE_COLUMN_CANDIDATES, "open": OPEN_COLUMN_CANDIDATES,
            "high": HIGH_COLUMN_CANDIDATES, "low": LOW_COLUMN_CANDIDATES,
            "close": CLOSE_COLUMN_CANDIDATES, "volume": VOLUME_COLUMN_CANDIDATES
        }

        for key, candidates in name_map.items():
            for cand_name in candidates:
                try:
                    indices[key] = column_names.index(cand_name)
                    break # Found preferred candidate
                except ValueError:
                    continue # Not found, try next candidate
        return indices

    async def get_symbols(self, market: str) -> List[str]:
        # Symbol discovery for Nasdaq Data Link is very different.
        # Users typically find DATABASE_CODE/DATASET_CODE on the NDL website.
        # This method could return a pre-defined list of popular codes for a given "market" category.
        logger.info(f"{self.__class__.__name__}: get_symbols for market '{market}'. This is non-trivial for NDL.")
        # Example:
        if market.lower() == "commodity_futures":
             # These are example CHRIS (Continuous S&P GSCI Commodity Index Series) dataset codes.
             # Many more exist.
            return [
                "CHRIS/CME_CL1", "CHRIS/CME_NG1", "CHRIS/CME_GC1", "CHRIS/CME_SI1",
                "CHRIS/CME_HG1", "CHRIS/CME_RB1", "CHRIS/CME_HO1",
                "CHRIS/ICE_B1", # Brent Crude
                "CHRIS/SGX_FEF1", # Iron Ore
                "CHRIS/CME_ZS1", # Soybeans
                "CHRIS/CME_ZC1", # Corn
                "CHRIS/CME_ZW1", # Wheat
            ]
        elif market.lower() == "selected_stocks":
            # Example: Old WIKI EOD database (free, but may not be updated)
            # Users would need to find specific codes.
             return ["WIKI/AAPL", "WIKI/MSFT", "WIKI/GOOGL"] # Illustrative
        elif market.lower() == "economic_data":
            return ["FRED/GDP", "FRED/UNRATE", "FRED/CPIAUCSL"] # US GDP, Unemployment, CPI

        logger.warning(f"{self.__class__.__name__}: No pre-defined symbol list for market '{market}'. Users must know NDL codes.")
        return []


    async def fetch_historical_ohlcv(
        self, symbol: str, timeframe: str, # `symbol` is the NDL code like "CHRIS/CME_CL1"
        since: Optional[int] = None, limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> List[OHLCVBar]:
        if timeframe != "1d": # Most NDL datasets are daily
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, f"Timeframe '{timeframe}' (Only '1d' supported directly)")

        if "/" not in symbol:
            raise PluginError(f"Invalid Nasdaq Data Link symbol format: '{symbol}'. Expected 'DATABASE_CODE/DATASET_CODE'.", self.provider_id)
        
        database_code, dataset_code = symbol.split('/', 1)
        endpoint = f"/datasets/{database_code}/{dataset_code}/data.json"
        
        api_params: Dict[str, Any] = {"order": "asc"} # Fetch oldest first
        if since is not None:
            api_params["start_date"] = datetime.fromtimestamp(since / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
        if params and "until_ms" in params: # 'until' from orchestrator maps to 'end_date'
             api_params["end_date"] = datetime.fromtimestamp(params["until_ms"] / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
        if limit is not None:
            api_params["limit"] = limit
        
        logger.debug(f"{self.__class__.__name__}: Fetching OHLCV for {symbol} (daily). Endpoint: {endpoint}, API Params: {api_params}")

        try:
            response_data = await self._request_api(endpoint, params=api_params)
            parsed_bars: List[OHLCVBar] = []

            if isinstance(response_data, dict) and "dataset_data" in response_data:
                dataset = response_data["dataset_data"]
                column_names = dataset.get("column_names")
                data_rows = dataset.get("data")

                if not column_names or not data_rows or not isinstance(data_rows, list):
                    logger.warning(f"{self.__class__.__name__}: Missing 'column_names' or 'data' in response for {symbol}.")
                    return []

                col_indices = self._get_column_indices(column_names)
                
                date_idx = col_indices["date"]
                open_idx, high_idx, low_idx = col_indices["open"], col_indices["high"], col_indices["low"]
                close_idx, volume_idx = col_indices["close"], col_indices["volume"]

                if date_idx is None:
                    raise PluginError(f"Could not find 'Date' column for {symbol}. Columns: {column_names}", self.provider_id)

                for row in data_rows:
                    if not isinstance(row, list) or len(row) <= max(filter(None, col_indices.values()), default=0): # Check row length
                        logger.warning(f"{self.__class__.__name__}: Skipping malformed row for {symbol}: {row}")
                        continue
                    try:
                        ts_ms = self._parse_ndl_timestamp(row[date_idx])
                        
                        # Helper to safely get float from row or default to 0.0 if None/missing/unparsable
                        def get_float_val(idx: Optional[int], default_val: float = 0.0) -> float:
                            if idx is None or row[idx] is None: return default_val
                            try: return float(row[idx])
                            except (ValueError, TypeError): return default_val

                        open_val = get_float_val(open_idx)
                        high_val = get_float_val(high_idx)
                        low_val = get_float_val(low_idx)
                        close_val = get_float_val(close_idx)
                        volume_val = get_float_val(volume_idx)
                        
                        # If essential OHLC values are missing (all default to 0.0), it might not be a valid bar
                        if open_idx is not None and open_val == 0.0 and \
                           high_idx is not None and high_val == 0.0 and \
                           low_idx is not None and low_val == 0.0 and \
                           close_idx is not None and close_val == 0.0 and \
                           not (open_idx is None and high_idx is None and low_idx is None and close_idx is None): # Ensure they were expected
                             logger.debug(f"{self.__class__.__name__}: Potentially empty OHLC data for row in {symbol}: {row}, using defaults.")
                        
                        parsed_bars.append({
                            "timestamp": ts_ms, "open": open_val, "high": high_val,
                            "low": low_val, "close": close_val, "volume": volume_val,
                        })
                    except (IndexError, TypeError, ValueError) as e_parse:
                        logger.warning(f"{self.__class__.__name__}: Error parsing row for {symbol}: {row}. Error: {e_parse}. Skipping.", exc_info=False)
            
            # Data is already sorted if order=asc was used
            logger.info(f"{self.__class__.__name__}: Fetched {len(parsed_bars)} OHLCV bars for {symbol} (daily).")
            return parsed_bars
        except PluginError as e:
            # NDL API might return specific error codes for "dataset not found"
            if e.original_exception and isinstance(e.original_exception, aiohttp.ClientResponseError) and e.original_exception.status == 404:
                logger.info(f"{self.__class__.__name__}: Dataset '{symbol}' not found (API 404).")
                return []
            if "QECx02" in str(e): # Invalid dataset code
                 logger.info(f"{self.__class__.__name__}: Dataset '{symbol}' not found (QECx02).")
                 return []
            raise
        except Exception as e:
            logger.error(f"{self.__class__.__name__}: Unexpected error fetching OHLCV for {symbol}: {e}", exc_info=True)
            raise PluginError(f"Unexpected error fetching OHLCV for {symbol}: {e}", self.provider_id, e) from e


    async def fetch_latest_ohlcv(self, symbol: str, timeframe: str = "1d") -> Optional[OHLCVBar]:
        if timeframe != "1d":
            raise PluginFeatureNotSupportedError(self.plugin_key, self.provider_id, f"Timeframe '{timeframe}' (Only '1d' supported)")
        
        logger.debug(f"{self.__class__.__name__}: Fetching latest '1d' bar for NDL code '{symbol}'.")
        try:
            # Fetch last 1 bar, ordered descending to get the latest, then reverse if needed for parsing logic
            # Or fetch last 1 bar, ordered ascending, and take that one.
            # NDL's `limit` parameter works with `order=desc` to get the latest.
            # However, our `Workspace_historical_ohlcv` assumes `order=asc`.
            # Let's call it with a recent `start_date` and `limit=1` with `order=asc`.
            
            # Look back N days to ensure we find at least one data point if today has no data yet.
            start_date_str = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
            end_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            bars = await self.fetch_historical_ohlcv(
                symbol, timeframe, 
                # Since we fetch `order=asc`, a limit of 1 with a start_date in the past
                # won't give the latest. We need to fetch a range and take the last.
                params={"start_date": start_date_str, "end_date": end_date_str}, # fetch_historical_ohlcv expects until_ms
                limit=10 # Fetch a few bars to ensure we get the actual latest
            )
            if bars:
                latest_bar = bars[-1] # Since fetch_historical_ohlcv now sorts ascending
                logger.info(f"{self.__class__.__name__}: Fetched latest '1d' bar for {symbol} @ {format_timestamp_to_iso(latest_bar['timestamp'])}.")
                return latest_bar
            logger.warning(f"{self.__class__.__name__}: No latest '1d' bar found for {symbol}.")
            return None
        except PluginError as e:
            logger.error(f"{self.__class__.__name__}: PluginError fetching latest bar for {symbol}: {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"{self.__class__.__name__}: Unexpected error fetching latest bar for {symbol}: {e}", exc_info=True)
            return None

    async def get_market_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        # `symbol` is the NDL code like "CHRIS/CME_CL1"
        current_time = time.monotonic()
        cached_data, cache_timestamp = self._dataset_metadata_cache.get(symbol, (None, 0.0))

        if cached_data and (current_time - cache_timestamp < DATASET_METADATA_CACHE_TTL_SECONDS):
            return cached_data
        
        if "/" not in symbol:
            logger.warning(f"{self.__class__.__name__}: Invalid NDL symbol format for metadata: '{symbol}'.")
            return None
            
        database_code, dataset_code = symbol.split('/', 1)
        endpoint = f"/datasets/{database_code}/{dataset_code}/metadata.json"
        
        logger.debug(f"{self.__class__.__name__}: Fetching metadata for NDL code '{symbol}'.")
        try:
            response_data = await self._request_api(endpoint) # Returns a dict
            if isinstance(response_data, dict) and "dataset" in response_data:
                dataset_info = response_data["dataset"]
                self._dataset_metadata_cache[symbol] = (dataset_info, current_time)
                logger.info(f"{self.__class__.__name__}: Fetched and cached metadata for '{symbol}'.")
                return dataset_info # This contains name, description, column_names, frequency etc.
            
            logger.warning(f"{self.__class__.__name__}: No valid 'dataset' info in metadata response for '{symbol}'. Resp: {str(response_data)[:200]}")
            self._dataset_metadata_cache[symbol] = (None, current_time)
            return None
        except PluginError as e:
            if (e.original_exception and isinstance(e.original_exception, aiohttp.ClientResponseError) and e.original_exception.status == 404) or \
               ("QECx02" in str(e)): # Dataset not found
                logger.info(f"{self.__class__.__name__}: Metadata not found for NDL code '{symbol}' (API error).")
                self._dataset_metadata_cache[symbol] = (None, current_time)
                return None
            logger.error(f"{self.__class__.__name__}: PluginError fetching metadata for '{symbol}': {e}", exc_info=False)
            if isinstance(e, AuthenticationPluginError): raise
            return None
        except Exception as e:
            logger.error(f"{self.__class__.__name__}: Unexpected error fetching metadata for '{symbol}': {e}", exc_info=True)
            return None

    async def validate_symbol(self, symbol: str) -> bool:
        # `symbol` is the NDL code
        logger.debug(f"{self.__class__.__name__}: Validating NDL code '{symbol}'.")
        try:
            market_info = await self.get_market_info(symbol) # This will try to fetch metadata
            return market_info is not None
        except Exception:
            logger.debug(f"{self.__class__.__name__}: NDL code '{symbol}' failed validation (metadata fetch failed). Assuming invalid.")
            return False

    async def get_supported_timeframes(self) -> Optional[List[str]]:
        # Most Nasdaq Data Link datasets are daily. Some might be weekly/monthly/quarterly/annual.
        # Intraday is rare for their typical dataset offerings.
        return self._supported_timeframes_cache # Defaults to ["1d"]

    async def get_fetch_ohlcv_limit(self) -> int:
        # NDL API for datasets doesn't have a hard limit like "max 5000 bars".
        # It's more about the date range and overall usage quotas.
        # For a single call, you can often get many years of daily data if available.
        # Let's return a conceptual large number.
        return self._fetch_limit_cache or 20000 

    async def get_supported_features(self) -> Dict[str, bool]:
        return {
            "watch_ticks": False,
            "fetch_trades": False, 
            "trading_api": False, 
            "get_market_info": True, # Fetches dataset metadata
            "validate_symbol": True, # Validates if dataset code is retrievable
            "get_supported_timeframes": True, # Primarily daily
            "get_fetch_ohlcv_limit": True,
        }

    async def close(self) -> None:
        logger.info(f"{self.__class__.__name__} '{self.provider_id}': Closing instance resources.")
        async with self._session_lock:
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                except Exception as e_close:
                    logger.error(f"{self.__class__.__name__} '{self.provider_id}': Error closing ClientSession: {e_close}", exc_info=True)
            self._session = None
        
        self._dataset_metadata_cache.clear()
        logger.info(f"{self.__class__.__name__} '{self.provider_id}': Session closed and caches cleared.")