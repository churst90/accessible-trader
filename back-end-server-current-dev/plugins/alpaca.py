# plugins/alpaca.py

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Coroutine, Callable

import aiohttp
from .base import MarketPlugin, PluginError, PluginFeatureNotSupportedError 
# from utils.timeframes import TIMEFRAME_PATTERN, UNIT_MS # Not strictly used here if only 1Min direct fetch

logger = logging.getLogger("AlpacaPlugin")

ALPACA_DATA_URL_V2 = "https://data.alpaca.markets/v2"
ALPACA_TRADE_URL_V2 = "https://api.alpaca.markets/v2" 
ALPACA_PAPER_TRADE_URL_V2 = "https://paper-api.alpaca.markets/v2"

class AlpacaPlugin(MarketPlugin):
    plugin_key = "alpaca"
    supported_markets = ["stocks"]
    plugin_version = "0.1.3" # Version bump for provider standardization

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.api_secret = api_secret or os.getenv("ALPACA_API_SECRET")

        if not self.api_key or not self.api_secret:
            # Log the warning but allow instantiation for discovery, actual calls will fail later
            logger.warning("Alpaca API key & secret not found in env or args. Operations requiring auth will fail.")
        
        self.data_base_url = ALPACA_DATA_URL_V2
        self.trade_base_url = ALPACA_TRADE_URL_V2 
        self._session_data: Optional[aiohttp.ClientSession] = None
        logger.info("AlpacaPlugin initialized.")

    async def _ensure_auth(self):
        """Ensures API keys are present before making an authenticated call."""
        if not self.api_key or not self.api_secret:
            raise PluginError("Alpaca API key and secret are required for this operation but not configured.")

    async def _get_data_session(self) -> aiohttp.ClientSession:
        await self._ensure_auth() # Ensure keys are available before creating session
        if self._session_data is None or self._session_data.closed:
            headers = {"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.api_secret}
            self._session_data = aiohttp.ClientSession(headers=headers)
            logger.info("Created new aiohttp session for Alpaca data.")
        return self._session_data

    async def get_exchanges(self) -> List[str]:
        return ["alpaca"] 

    async def get_symbols(self, provider: str) -> List[str]: # Standardized to provider
        if provider != "alpaca":
            raise PluginError(f"Alpaca plugin only supports 'alpaca' as provider, got '{provider}'")
        
        await self._ensure_auth() # Ensure keys before making API call
        session = None # Use a temporary session for this specific call
        try:
            headers = {"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.api_secret}
            session = aiohttp.ClientSession(headers=headers)
            url = f"{self.trade_base_url}/assets" 
            params = {"status": "active", "asset_class": "us_equity", "tradable": "true"}
            
            logger.debug(f"Fetching Alpaca symbols from {url} with params {params}")
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Alpaca assets API error {resp.status}: {text}")
                    raise PluginError(f"Alpaca assets API error {resp.status}: {text}")
                data = await resp.json()
            
            symbols = [asset["symbol"] for asset in data if asset.get("tradable", False)]
            logger.info(f"Fetched {len(symbols)} symbols from Alpaca.")
            return sorted(symbols)
        except aiohttp.ClientError as e:
            logger.error(f"HTTP client error fetching Alpaca symbols: {e}", exc_info=True)
            raise PluginError(f"Failed to connect to Alpaca for symbols: {e}") from e
        except Exception as e:
            logger.error(f"Error processing Alpaca symbols: {e}", exc_info=True)
            raise PluginError(f"Failed to get symbols from Alpaca: {e}") from e
        finally: 
            if session: await session.close()

    async def fetch_historical_ohlcv(
        self, provider: str, symbol: str, timeframe: str, 
        since: Optional[int] = None, limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None 
    ) -> List[Dict[str, Any]]:
        if provider != "alpaca": raise PluginError(f"Alpaca plugin supports 'alpaca', got '{provider}'")
        
        alpaca_tf = "1Min" 
        if timeframe != '1m':
            logger.warning(f"Alpaca fetch_historical_ohlcv requested {timeframe}, will fetch '{alpaca_tf}'.")
        
        sess = await self._get_data_session() # Ensures keys are present
        url = f"{self.data_base_url}/stocks/{symbol}/bars"
        api_params: Dict[str, Any] = {"timeframe": alpaca_tf, "adjustment": "raw"}
        if limit: api_params["limit"] = min(limit, 10000) 
        if since: api_params["start"] = datetime.fromtimestamp(since / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        if params: api_params.update(params)

        logger.debug(f"Fetching Alpaca OHLCV: {url} with params {api_params}")
        try:
            async with sess.get(url, params=api_params) as resp:
                if resp.status != 200: 
                    text = await resp.text()
                    logger.error(f"Alpaca bars API error {resp.status} for {symbol}: {text}")
                    raise PluginError(f"Alpaca bars API error {resp.status} for {symbol}: {text}")
                payload = await resp.json()
            
            bars_data = payload.get("bars", []) or []
            ohlcv_list = []
            for b in bars_data:
                try:
                    ts_dt = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
                    ohlcv_list.append({
                        "timestamp": int(ts_dt.timestamp() * 1000), "open": float(b["o"]),
                        "high": float(b["h"]), "low": float(b["l"]), "close": float(b["c"]),
                        "volume": float(b["v"]),
                    })
                except (ValueError, TypeError, KeyError) as conv_err: 
                    logger.warning(f"Skipping Alpaca bar for {symbol}: {conv_err} in bar {b}")
            ohlcv_list.sort(key=lambda x: x['timestamp'])
            return ohlcv_list
        except aiohttp.ClientError as e:
            logger.error(f"HTTP client error fetching Alpaca OHLCV for {symbol}: {e}", exc_info=True)
            raise PluginError(f"Connection error fetching Alpaca OHLCV: {e}") from e
        except Exception as e:
            logger.error(f"Error processing Alpaca OHLCV for {symbol}: {e}", exc_info=True)
            raise PluginError(f"Failed to process OHLCV from Alpaca for {symbol}: {e}") from e

    async def fetch_latest_ohlcv(
        self, provider: str, symbol: str, timeframe: str 
    ) -> Optional[Dict[str, Any]]:
        if provider != "alpaca": raise PluginError(f"Alpaca plugin supports 'alpaca', got '{provider}'")
        # MarketService expects '1m'
        if timeframe != '1m': logger.warning(f"Alpaca fetch_latest_ohlcv called for {timeframe}, will fetch 1m.")
        try:
            recent_bars = await self.fetch_historical_ohlcv(provider, symbol, '1m', limit=2, params=None) # Use standardized call
            return max(recent_bars, key=lambda x: x['timestamp']) if recent_bars else None
        except PluginError as e: # Catch PluginError from fetch_historical_ohlcv
            logger.warning(f"PluginError fetching latest Alpaca bar for {symbol}: {e}") # Don't show exc_info for PluginError
            return None
        except Exception as e:
            logger.warning(f"Unexpected error fetching latest Alpaca bar for {symbol}: {e}", exc_info=True)
            return None
            
    async def close(self) -> None:
        if self._session_data and not self._session_data.closed:
            await self._session_data.close()
            logger.info("Closed Alpaca data HTTP session.")
        self._session_data = None
    
    # Other optional methods remain as stubs raising PluginFeatureNotSupportedError
    async def watch_ticks(self, provider: str, symbol: str, callback: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]) -> None: raise PluginFeatureNotSupportedError(self.plugin_name, "watch_ticks")
    async def fetch_trades(self, provider: str, symbol: str,since: Optional[int]=None, limit: Optional[int]=100) -> List[Dict[str,Any]]: raise PluginFeatureNotSupportedError(self.plugin_name, "fetch_trades")
    async def get_trade_client(self, user_api_key: str, user_api_secret: str, user_api_passphrase: Optional[str]=None, is_testnet: bool=False, **kwargs) -> Any: raise PluginFeatureNotSupportedError(self.plugin_name, "get_trade_client (trading)")
    async def place_order(self, trade_client: Any, provider: str, symbol: str, order_type: str, side: str, amount: float, price: Optional[float]=None, params: Optional[Dict[str,Any]]=None) -> Dict[str,Any]: raise PluginFeatureNotSupportedError(self.plugin_name, "place_order (trading)")
    async def fetch_balance(self, trade_client: Any, provider: str, params: Optional[Dict[str,Any]]=None) -> Dict[str,Any]: raise PluginFeatureNotSupportedError(self.plugin_name, "fetch_balance (trading)")
    async def fetch_open_orders(self, trade_client: Any, provider: str, symbol: Optional[str]=None,since: Optional[int]=None,limit: Optional[int]=None,params: Optional[Dict[str,Any]]=None) -> List[Dict[str,Any]]: raise PluginFeatureNotSupportedError(self.plugin_name, "fetch_open_orders (trading)")
    async def get_supported_features(self) -> Dict[str, bool]: return {"watch_ticks": False, "fetch_trades": False, "trading_api": False}