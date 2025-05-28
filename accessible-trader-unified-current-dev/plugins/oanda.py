# plugins/oanda.py

import asyncio
import logging
import os
import time
import random # For retry jitter
from datetime import datetime, timezone, timedelta
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

OANDA_BASE_URL_LIVE = "https://api-fxtrade.oanda.com/v3"
OANDA_BASE_URL_PRACTICE = "https://api-fxpractice.oanda.com/v3"

DEFAULT_OANDA_RETRY_COUNT = 3
DEFAULT_OANDA_RETRY_DELAY_BASE_S = 1.5
OANDA_MAX_CANDLES_PER_REQUEST = 5000

# Cache TTLs
INSTRUMENTS_CACHE_TTL_SECONDS = 12 * 3600  # 12 hours for instrument lists

class OANDAPlugin(MarketPlugin):
    plugin_key: str = "oanda"
    # OANDA provides Forex and CFDs on indices, commodities, metals, bonds
    supported_markets: List[str] = ["forex", "cfd_index", "cfd_commodity", "cfd_metal", "cfd_bond"]

    def __init__(
        self,
        provider_id: str, # Expected to be "oanda"
        api_key: Optional[str] = None, # OANDA Personal Access Token
        api_secret: Optional[str] = None, # Not directly used, but we need Account ID
        api_passphrase: Optional[str] = None, # Not used. api_passphrase can store Account ID.
        is_testnet: bool = False, # True for fxTrade Practice environment
        request_timeout: int = 30000,
        verbose_logging: bool = False,
        retry_count: int = DEFAULT_OANDA_RETRY_COUNT,
        retry_delay_base: float = DEFAULT_OANDA_RETRY_DELAY_BASE_S,
        **kwargs: Any # To potentially pass account_id if not in passphrase
    ):
        if provider_id.lower() != "oanda":
            raise PluginError(
                message=f"OANDAPlugin initialized with incorrect provider_id: '{provider_id}'. Expected 'oanda'.",
                provider_id=provider_id
            )

        resolved_api_key = api_key or os.getenv("OANDA_API_TOKEN")
        # OANDA requires an Account ID. We can pass it via api_passphrase or a custom kwarg.
        self.account_id: Optional[str] = api_passphrase or kwargs.get("oanda_account_id") or os.getenv("OANDA_ACCOUNT_ID")


        super().__init__(
            provider_id="oanda",
            api_key=resolved_api_key,
            api_secret=None, # Not used by OANDA in this context
            api_passphrase=self.account_id, # Store account_id here for consistency if desired
            is_testnet=is_testnet,
            request_timeout=request_timeout,
            verbose_logging=verbose_logging,
            **kwargs
        )

        self._base_url = OANDA_BASE_URL_PRACTICE if self.is_testnet else OANDA_BASE_URL_LIVE
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        
        self.retry_count = retry_count
        self.retry_delay_base = retry_delay_base

        # Cache for account instruments: Key "instruments", Value: (list_of_instrument_dicts, timestamp)
        self._instruments_cache: Tuple[Optional[List[Dict[str, Any]]], float] = (None, 0.0)
        self._supported_timeframes_cache: Optional[List[str]] = None
        self._fetch_limit_cache: Optional[int] = OANDA_MAX_CANDLES_PER_REQUEST

        if not self.api_key:
            logger.warning(f"OANDAPlugin for '{self.provider_id}' initialized without an API Token.")
        if not self.account_id:
            logger.warning(f"OANDAPlugin for '{self.provider_id}' initialized without an Account ID. Many operations will fail.")
        
        logger.info(
            f"OANDAPlugin instance initialized. Provider: '{self.provider_id}', "
            f"Environment: {'Practice (Testnet)' if self.is_testnet else 'Live'}, "
            f"API Token Provided: {bool(self.api_key)}, Account ID: {self.account_id if self.account_id else 'Not Provided'}."
        )

    @classmethod
    def get_plugin_key(cls) -> str:
        return cls.plugin_key

    @classmethod
    def get_supported_markets(cls) -> List[str]:
        return cls.supported_markets

    @classmethod
    def list_configurable_providers(cls) -> List[str]:
        return ["oanda"]

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session is None or self._session.closed:
                if not self.api_key:
                    raise AuthenticationPluginError(self.provider_id, "OANDA API Token is missing for session creation.")
                
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                    # "Account-ID" header can also be used for some endpoints, but often it's in path
                }
                timeout_seconds = self.request_timeout / 1000.0
                timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
                logger.debug(f"OANDAPlugin '{self.provider_id}': New aiohttp.ClientSession created.")
            return self._session

    async def _request_api(
        self,
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None # For POST/PUT
    ) -> Any:
        session = await self._get_session() # Ensures headers are set up
        url = f"{self._base_url}{endpoint}"
        
        response_text_snippet = ""
        last_exception: Optional[Exception] = None

        for attempt in range(self.retry_count + 1):
            try:
                if self.verbose_logging:
                    logger.debug(f"OANDAPlugin '{self.provider_id}': Req {method} {url}, Prms: {params}, Data: {data} (Atmpt {attempt+1})")

                async with session.request(method, url, params=params, json=data) as response:
                    response_text = await response.text()
                    response_text_snippet = response_text[:500]

                    if self.verbose_logging:
                        logger.debug(f"OANDAPlugin '{self.provider_id}': Resp Status {response.status} from {url}. Body: {response_text_snippet}")
                    
                    parsed_json = None
                    if response.content_type == 'application/json':
                        try:
                            parsed_json = await response.json()
                        except Exception as json_err:
                             logger.warning(f"OANDAPlugin '{self.provider_id}': Failed to parse JSON response from {url}, status {response.status}. Error: {json_err}. Snippet: {response_text_snippet}")
                             if response.status < 400: # If successful status but bad JSON
                                 raise PluginError("Received non-JSON success response from OANDA.", self.provider_id)
                             # If error status and bad JSON, let status code handling take over.


                    if response.status == 401: # Unauthorized
                        msg = parsed_json.get("errorMessage", response_text_snippet) if parsed_json else response_text_snippet
                        raise AuthenticationPluginError(self.provider_id, f"OANDA API Error 401 (Unauthorized): {msg}")
                    if response.status == 403: # Forbidden
                        msg = parsed_json.get("errorMessage", response_text_snippet) if parsed_json else response_text_snippet
                        raise AuthenticationPluginError(self.provider_id, f"OANDA API Error 403 (Forbidden): {msg}")
                    if response.status == 404: # Not Found
                        msg = parsed_json.get("errorMessage", response_text_snippet) if parsed_json else response_text_snippet
                        raise PluginError(f"OANDA API Error 404 (Not Found): {msg}", self.provider_id)
                    if response.status == 429: # Too Many Requests / Rate Limit
                        msg = parsed_json.get("errorMessage", response_text_snippet) if parsed_json else response_text_snippet
                        raise NetworkPluginError(self.provider_id, f"OANDA API Error 429 (Rate Limit): {msg}")
                    
                    # For other client errors (4xx) or server errors (5xx)
                    if response.status >= 400:
                        msg = parsed_json.get("errorMessage", response_text_snippet) if parsed_json else response_text_snippet
                        logger.error(f"OANDAPlugin '{self.provider_id}': API error {response.status} for {url}. Message: {msg}")
                        response.raise_for_status() # Will raise ClientResponseError

                    if response.status == 204: return {} # No content
                    
                    return parsed_json if parsed_json else await response.json(content_type=None) # Should be parsed_json if content_type was application/json

            except (NetworkPluginError, aiohttp.ClientConnectionError, aiohttp.ServerDisconnectedError, asyncio.TimeoutError) as e:
                last_exception = e
                if attempt == self.retry_count:
                    raise NetworkPluginError(self.provider_id, f"API call to {url} failed: {e}", e) from e
                delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.5)
                logger.warning(f"OANDAPlugin ('{self.provider_id}'): {type(e).__name__} for {url} (Atmpt {attempt+1}). Retrying in {delay:.2f}s.")
                await asyncio.sleep(delay)
            except AuthenticationPluginError: raise
            except PluginError: raise
            except aiohttp.ClientResponseError as e: # From raise_for_status
                logger.error(f"OANDAPlugin '{self.provider_id}': HTTP error {e.status} for {url}: {e.message}. Resp: {response_text_snippet}", exc_info=False)
                if e.status >= 500 and attempt < self.retry_count: # Retry server errors
                    last_exception = e
                    delay = self.retry_delay_base * (2 ** attempt) + random.uniform(0, self.retry_delay_base * 0.5)
                    await asyncio.sleep(delay)
                    continue
                raise PluginError(f"HTTP error {e.status}: {e.message}", self.provider_id, e) from e
            except Exception as e:
                logger.error(f"OANDAPlugin '{self.provider_id}': Unexpected error for {url}: {e}. Resp: {response_text_snippet}", exc_info=True)
                last_exception = e
                if attempt == self.retry_count:
                    raise PluginError(f"Unexpected API error: {e}", self.provider_id, e) from e
                delay = self.retry_delay_base * (2 ** attempt)
                await asyncio.sleep(delay)
        
        if last_exception:
            raise PluginError(f"API call failed for {url}. Last: {last_exception}", self.provider_id, last_exception)
        raise PluginError(f"API call failed unexpectedly for {url}", self.provider_id)

    def _map_internal_timeframe_to_oanda_granularity(self, internal_timeframe: str) -> str:
        """Maps internal timeframe string to OANDA's 'granularity' codes."""
        tf = internal_timeframe.upper() # OANDA granularities are uppercase
        # Seconds: S5, S10, S15, S30
        # Minutes: M1, M2, M4, M5, M10, M15, M30
        # Hours: H1, H2, H3, H4, H6, H8, H12
        # Day: D, Week: W, Month: M
        
        # Simple mapping, assuming internal format like "1m", "5s", "1h", "1d", "1w", "1mo"
        if tf.endswith("S") and tf[:-1].isdigit(): return tf
        if tf.endswith("M") and tf[:-1].isdigit(): return tf # Covers M1, M15 etc.
        if tf.endswith("H") and tf[:-1].isdigit(): return tf
        if tf == "D" or tf == "1D": return "D"
        if tf == "W" or tf == "1W": return "W"
        if tf == "MO" or tf == "1MO" or tf == "M": return "M" # OANDA uses 'M' for Month

        # Fallback for common patterns if not perfectly matched
        if 'M' in tf and 'MIN' not in tf.upper(): tf = tf.replace('M', 'M') # e.g. 1m -> M1
        if 'H' in tf and 'HOUR' not in tf.upper(): tf = tf.replace('H', 'H')
        if 'D' in tf and 'DAY' not in tf.upper(): tf = 'D'
        
        # Check against known granularities
        known_granularities = [
            "S5", "S10", "S15", "S30", "M1", "M2", "M4", "M5", "M10", "M15", "M30",
            "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D", "W", "M"
        ]
        if tf in known_granularities:
            return tf

        logger.warning(f"OANDAPlugin: Could not map internal timeframe '{internal_timeframe}' to OANDA granularity. Defaulting to 'M1'.")
        return "M1" # Default fallback

    def _parse_oanda_timestamp(self, rfc3339_str: str) -> int:
        """Parses OANDA's RFC3339 timestamp string to UTC milliseconds."""
        try:
            # Handle potential Z and varying fractional seconds
            if rfc3339_str.endswith('Z'):
                dt_obj = datetime.fromisoformat(rfc3339_str[:-1] + '+00:00')
            else:
                dt_obj = datetime.fromisoformat(rfc3339_str)
            
            if dt_obj.tzinfo is None: # If somehow still naive, assume UTC
                dt_obj = dt_obj.replace(tzinfo=timezone.utc)
            
            return int(dt_obj.astimezone(timezone.utc).timestamp() * 1000)
        except Exception as e:
            logger.error(f"OANDAPlugin: Error parsing OANDA timestamp '{rfc3339_str}': {e}")
            raise ValueError(f"Invalid OANDA timestamp format: {rfc3339_str}")


    async def get_symbols(self, market: str) -> List[str]:
        if not self.account_id:
            raise AuthenticationPluginError(self.provider_id, "OANDA Account ID is required to fetch instruments.")

        current_time = time.monotonic()
        cached_instruments, cache_timestamp = self._instruments_cache
        if cached_instruments and (current_time - cache_timestamp < INSTRUMENTS_CACHE_TTL_SECONDS):
            logger.debug(f"OANDAPlugin: Returning instruments from cache for account {self.account_id}.")
        else:
            logger.debug(f"OANDAPlugin: Fetching instruments for account {self.account_id}.")
            try:
                response = await self._request_api(f"/accounts/{self.account_id}/instruments")
                if response and "instruments" in response and isinstance(response["instruments"], list):
                    cached_instruments = response["instruments"]
                    self._instruments_cache = (cached_instruments, current_time)
                    logger.info(f"OANDAPlugin: Fetched and cached {len(cached_instruments)} instruments for account {self.account_id}.")
                else:
                    logger.warning(f"OANDAPlugin: No 'instruments' list in response for account {self.account_id}. Response: {response}")
                    cached_instruments = [] # Cache empty on bad response
                    self._instruments_cache = (cached_instruments, current_time)
            except PluginError as e:
                logger.error(f"OANDAPlugin: PluginError fetching instruments: {e}", exc_info=False)
                if cached_instruments: return [inst['name'] for inst in cached_instruments if inst.get('type', '').lower() == market.lower() or market.lower() in inst.get('type','').lower()] # Return stale
                raise
            except Exception as e:
                logger.error(f"OANDAPlugin: Unexpected error fetching instruments: {e}", exc_info=True)
                if cached_instruments: return [inst['name'] for inst in cached_instruments if inst.get('type', '').lower() == market.lower() or market.lower() in inst.get('type','').lower()]
                raise PluginError(f"Unexpected error fetching instruments: {e}", self.provider_id, e) from e
        
        # Filter symbols based on the requested market
        symbols_list: List[str] = []
        if cached_instruments:
            normalized_market = market.lower()
            for instrument_data in cached_instruments:
                instrument_type = instrument_data.get("type", "").upper() # CURRENCY, CFD
                instrument_name = instrument_data.get("name") # e.g. EUR_USD, XAU_USD, SPX500_USD
                # OANDA's type is CURRENCY or CFD. For CFDs, the name indicates the underlying.
                # We need a heuristic to map to our `supported_markets`.
                if not instrument_name: continue

                # Basic mapping logic
                maps_to_market = False
                if normalized_market == "forex" and instrument_type == "CURRENCY":
                    maps_to_market = True
                elif normalized_market == "cfd_index" and instrument_type == "CFD" and \
                     any(kw in instrument_name.upper() for kw in ["SPX", "NAS", "DAX", "UK100", "JP225"]): # Example keywords
                    maps_to_market = True
                elif normalized_market == "cfd_commodity" and instrument_type == "CFD" and \
                     any(kw in instrument_name.upper() for kw in ["OIL", "BCO", "XTI", "XCU", "NATGAS"]):
                    maps_to_market = True
                elif normalized_market == "cfd_metal" and instrument_type == "CFD" and \
                     any(kw in instrument_name.upper() for kw in ["XAU", "XAG", "XPT", "XPD"]): # Gold, Silver, Platinum, Palladium
                    maps_to_market = True
                elif normalized_market == "cfd_bond" and instrument_type == "CFD" and \
                     any(kw in instrument_name.upper() for kw in ["BUND", "BTP", "TRY"]): # Example bond CFDs
                    maps_to_market = True
                
                if maps_to_market:
                    symbols_list.append(instrument_name)
        
        logger.info(f"OANDAPlugin: Returning {len(symbols_list)} symbols for market '{market}'.")
        return sorted(list(set(symbols_list)))

    async def fetch_historical_ohlcv(
        self, symbol: str, timeframe: str,
        since: Optional[int] = None, limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None # e.g. price="BMA" for Bid/Mid/Ask
    ) -> List[OHLCVBar]:
        oanda_granularity = self._map_internal_timeframe_to_oanda_granularity(timeframe)
        
        api_params: Dict[str, Any] = {
            "granularity": oanda_granularity,
            "price": params.get("price_component", "M") if params else "M", # Default to Midpoint candles
        }
        # OANDA uses `count` OR `from`/`to`. `count` takes precedence if both specified.
        # `limit` from our system maps to `count`.
        if limit is not None and limit > 0:
            api_params["count"] = min(limit, OANDA_MAX_CANDLES_PER_REQUEST)
        elif since is None: # If no limit and no since, fetch default count
             api_params["count"] = 500 # OANDA default if no count/from/to, let's be explicit

        if since is not None:
            api_params["from"] = datetime.fromtimestamp(since / 1000.0, tz=timezone.utc).isoformat()
        
        # Handle 'until' if passed from DataOrchestrator via params
        if params and "until_ms" in params:
            api_params["to"] = datetime.fromtimestamp(params["until_ms"] / 1000.0, tz=timezone.utc).isoformat()

        logger.debug(f"OANDAPlugin: Fetching OHLCV for {symbol} @ {oanda_granularity}. API Params: {api_params}")

        try:
            response_data = await self._request_api(f"/instruments/{symbol}/candles", params=api_params)
            parsed_bars: List[OHLCVBar] = []

            if isinstance(response_data, dict) and "candles" in response_data and isinstance(response_data["candles"], list):
                for candle_data in response_data["candles"]:
                    if not isinstance(candle_data, dict) or not candle_data.get("complete", False): # Process only complete candles
                        if not candle_data.get("complete", True): # Log if explicitly incomplete
                            logger.debug(f"OANDAPlugin: Skipping incomplete candle for {symbol}: {candle_data.get('time')}")
                        continue 

                    price_kind = api_params["price"].lower() # m, b, or a
                    ohlc_details = candle_data.get(price_kind)
                    if not ohlc_details: # If "m" was requested but not there, try "mid" (OANDA v20 uses "mid", "bid", "ask")
                        if price_kind == "m": ohlc_details = candle_data.get("mid")
                        elif price_kind == "b": ohlc_details = candle_data.get("bid")
                        elif price_kind == "a": ohlc_details = candle_data.get("ask")
                    
                    if not ohlc_details or not all(k in ohlc_details for k in ["o", "h", "l", "c"]):
                        logger.warning(f"OANDAPlugin: Missing OHLC details in '{price_kind}' candle for {symbol}: {candle_data}")
                        continue
                    try:
                        ts_ms = self._parse_oanda_timestamp(candle_data["time"])
                        parsed_bars.append({
                            "timestamp": ts_ms,
                            "open": float(ohlc_details["o"]),
                            "high": float(ohlc_details["h"]),
                            "low": float(ohlc_details["l"]),
                            "close": float(ohlc_details["c"]),
                            "volume": float(candle_data.get("volume", 0.0)), # Tick volume
                        })
                    except (TypeError, ValueError, KeyError) as e_parse:
                        logger.warning(f"OANDAPlugin: Error parsing candle for {symbol}: {candle_data}. Error: {e_parse}. Skipping.", exc_info=False)
            
            # OANDA candles are typically oldest first. If not, sort:
            # parsed_bars.sort(key=lambda b: b['timestamp'])
            
            logger.info(f"OANDAPlugin: Fetched {len(parsed_bars)} OHLCV bars for {symbol}/{timeframe}.")
            return parsed_bars
        except PluginError as e:
             # OANDA error for "Instrument not found" or similar might be specific
            if e.original_exception and isinstance(e.original_exception, aiohttp.ClientResponseError) and e.original_exception.status == 400: # Bad Request can mean invalid instrument
                if "INVALID_INSTRUMENT" in str(e).upper() or "UNKNOWN_INSTRUMENT" in str(e).upper():
                    logger.info(f"OANDAPlugin: Instrument '{symbol}' not found (API error).")
                    return []
            raise
        except Exception as e:
            logger.error(f"OANDAPlugin: Unexpected error fetching OHLCV for {symbol}: {e}", exc_info=True)
            raise PluginError(f"Unexpected error fetching OHLCV for {symbol}: {e}", self.provider_id, e) from e

    async def fetch_latest_ohlcv(self, symbol: str, timeframe: str = "1m") -> Optional[OHLCVBar]:
        logger.debug(f"OANDAPlugin: Fetching latest '{timeframe}' bar for {symbol}.")
        try:
            # Fetch last 2 candles to ensure we get the most recent *complete* one.
            # `until` is implicitly now.
            bars = await self.fetch_historical_ohlcv(symbol, timeframe, limit=2) # Fetches last 2 available complete candles
            if bars:
                latest_bar = bars[-1] # The most recent of the two (or one if only one available)
                logger.info(f"OANDAPlugin: Fetched latest '{timeframe}' bar for {symbol} @ {format_timestamp_to_iso(latest_bar['timestamp'])}.")
                return latest_bar
            logger.warning(f"OANDAPlugin: No latest '{timeframe}' bar found for {symbol}.")
            return None
        except PluginError as e:
            logger.error(f"OANDAPlugin: PluginError fetching latest bar for {symbol}/{timeframe}: {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"OANDAPlugin: Unexpected error fetching latest bar for {symbol}/{timeframe}: {e}", exc_info=True)
            return None

    async def get_market_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        # OANDA doesn't have a "profile" like stocks. We fetch all instruments and find the specific one.
        current_time = time.monotonic()
        all_instruments, cache_timestamp = self._instruments_cache

        if not all_instruments or (current_time - cache_timestamp > INSTRUMENTS_CACHE_TTL_SECONDS):
            logger.debug(f"OANDAPlugin: Cache miss/stale for instrument list. Fetching for market info of {symbol}.")
            try:
                # This implicitly calls get_symbols logic if we refactor get_symbols to just return names
                # For now, explicitly fetch if needed.
                await self.get_symbols(market="forex") # Call get_symbols to populate cache if empty/stale. Market arg here is just for a full list.
                all_instruments, _ = self._instruments_cache # Re-fetch from cache
            except Exception as e:
                logger.error(f"OANDAPlugin: Failed to refresh instrument list for get_market_info({symbol}): {e}")
                return None
        
        if all_instruments:
            for inst_data in all_instruments:
                if inst_data.get("name") == symbol:
                    logger.info(f"OANDAPlugin: Found market info for instrument '{symbol}'.")
                    return inst_data # Returns the full instrument dictionary from OANDA
        
        logger.warning(f"OANDAPlugin: No market info found for instrument '{symbol}' in cached list.")
        return None

    async def validate_symbol(self, symbol: str) -> bool:
        logger.debug(f"OANDAPlugin: Validating symbol '{symbol}'.")
        try:
            instrument_info = await self.get_market_info(symbol) # This uses cached instrument list
            return instrument_info is not None and instrument_info.get("name") == symbol
        except Exception:
            logger.debug(f"OANDAPlugin: Symbol '{symbol}' failed validation. Assuming invalid.")
            return False

    async def get_supported_timeframes(self) -> Optional[List[str]]:
        if self._supported_timeframes_cache is None:
            # These are your internal representations that _map_internal_timeframe_to_oanda_granularity handles
            self._supported_timeframes_cache = [
                "5s", "10s", "15s", "30s",
                "1m", "2m", "4m", "5m", "10m", "15m", "30m",
                "1h", "2h", "3h", "4h", "6h", "8h", "12h",
                "1d", "1w", "1mo" # Using "1mo" for internal consistency
            ]
        return self._supported_timeframes_cache

    async def get_fetch_ohlcv_limit(self) -> int:
        return self._fetch_limit_cache or OANDA_MAX_CANDLES_PER_REQUEST

    async def get_supported_features(self) -> Dict[str, bool]:
        return {
            "watch_ticks": False, # OANDA has streaming, but this REST plugin doesn't implement it
            "fetch_trades": False, # OANDA v20 is primarily for rates/candles, not individual public trades
            "trading_api": True, # OANDA is a trading platform (not implemented in this data plugin)
            "get_market_info": True, # Via instrument list
            "validate_symbol": True,
            "get_supported_timeframes": True,
            "get_fetch_ohlcv_limit": True,
        }

    async def close(self) -> None:
        logger.info(f"OANDAPlugin '{self.provider_id}': Closing instance resources.")
        async with self._session_lock:
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                except Exception as e_close:
                    logger.error(f"OANDAPlugin '{self.provider_id}': Error closing ClientSession: {e_close}", exc_info=True)
            self._session = None
        
        # Clearing instrument cache on close might not be necessary if it's account-wide and long-lived
        # self._instruments_cache = (None, 0.0) 
        logger.info(f"OANDAPlugin '{self.provider_id}': Session closed.")