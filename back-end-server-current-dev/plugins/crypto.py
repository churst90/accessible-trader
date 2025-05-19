# plugins/crypto.py

import asyncio
import logging
from typing import Dict, List, Any, Callable, Coroutine, Optional, Tuple, Type
import time 

import ccxt.async_support as ccxt
from quart import current_app 

from .base import MarketPlugin, PluginError, PluginFeatureNotSupportedError # Uses MarketPlugin
from utils.cache import Cache 
from utils.timeframes import UNIT_MS # For fetch_latest_ohlcv staleness check

logger = logging.getLogger("CryptoPlugin")

# --- Configuration Constants ---
DEFAULT_REQUEST_TIMEOUT_CONFIG = "CCXT_REQUEST_TIMEOUT_MS" 
DEFAULT_LRU_CACHE_SIZE_CONFIG = "CRYPTO_PLUGIN_LRU_CACHE_SIZE" 
DEFAULT_RETRY_COUNT_CONFIG = "CRYPTO_PLUGIN_RETRY_COUNT" 
DEFAULT_RETRY_DELAY_BASE_CONFIG = "CRYPTO_PLUGIN_RETRY_DELAY_BASE_S"
LATEST_BAR_LOOKBACK_LIMIT = 5 

_exchange_instances: Dict[str, ccxt.Exchange] = {}
_exchange_access_order: List[str] = []


class CryptoPlugin(MarketPlugin): 
    plugin_key = "crypto"
    plugin_name = "Cryptocurrency Exchanges (via CCXT)"
    plugin_version = "0.5.3" # Incremented version for provider standardization
    supported_markets = ["crypto"]

    def __init__(self): 
        self._app_config: Dict[str, Any] = {}
        self.request_timeout: int = 30000
        self.lru_cache_size: int = 20 
        self.retry_count: int = 3
        self.retry_delay_base: float = 0.75
        self._cache: Optional[Cache] = None
        self._ccxt_verbose_logging: bool = False

        try:
            if current_app: 
                self._app_config = current_app.config
                self.request_timeout = int(self._app_config.get(DEFAULT_REQUEST_TIMEOUT_CONFIG, 30000))
                self.lru_cache_size = int(self._app_config.get(DEFAULT_LRU_CACHE_SIZE_CONFIG, 20))
                self.retry_count = int(self._app_config.get(DEFAULT_RETRY_COUNT_CONFIG, 3))
                self.retry_delay_base = float(self._app_config.get(DEFAULT_RETRY_DELAY_BASE_CONFIG, 0.75))
                self._cache = self._app_config.get("CACHE")
                self._ccxt_verbose_logging = bool(self._app_config.get('CCXT_VERBOSE_LOGGING', False))
                logger.info(f"CryptoPlugin configured using current_app.config. LRU: {self.lru_cache_size}, Timeout: {self.request_timeout}ms")
            else:
                logger.warning("CryptoPlugin initialized: current_app not found. Using default configurations.")
        except RuntimeError: 
            logger.warning("CryptoPlugin initialized: RuntimeError accessing current_app.config. Using defaults.")
        
        logger.info(
            f"CryptoPlugin instance created. CCXT: {getattr(ccxt, '__version__', 'unknown')}. "
            f"Exchanges available: {len(ccxt.exchanges)}."
        )

    async def _get_exchange_instance(self, provider_id: str) -> ccxt.Exchange: # Renamed for clarity internally
        exchange_id_lower = provider_id.lower() # CCXT uses lowercase exchange IDs
        if exchange_id_lower in _exchange_instances:
            if exchange_id_lower in _exchange_access_order: _exchange_access_order.remove(exchange_id_lower)
            _exchange_access_order.append(exchange_id_lower)
            return _exchange_instances[exchange_id_lower]
        if not hasattr(ccxt, exchange_id_lower): raise PluginError(f"Exchange '{exchange_id_lower}' not in CCXT.")
        try:
            exchange_class: Type[ccxt.Exchange] = getattr(ccxt, exchange_id_lower)
            instance: ccxt.Exchange = exchange_class({'timeout': self.request_timeout, 'enableRateLimit': True, 'verbose': self._ccxt_verbose_logging})
            logger.info(f"Created CCXT instance for {exchange_id_lower}.")
            if len(_exchange_instances) >= self.lru_cache_size and self.lru_cache_size > 0 and _exchange_access_order:
                old_id = _exchange_access_order.pop(0)
                old_inst = _exchange_instances.pop(old_id, None)
                if old_inst and hasattr(old_inst, 'close') and asyncio.iscoroutinefunction(old_inst.close):
                    asyncio.create_task(old_inst.close(), name=f"CCXTCloseEvict_{old_id}")
                    logger.info(f"Evicted and scheduled closure for CCXT instance: {old_id}")
            _exchange_instances[exchange_id_lower] = instance
            if exchange_id_lower not in _exchange_access_order: _exchange_access_order.append(exchange_id_lower)
            return instance
        except Exception as e: raise PluginError(f"Init CCXT for '{exchange_id_lower}' failed: {e}") from e

    async def _with_retries(
        self, async_fn: Callable[..., Coroutine[Any, Any, Any]], *args: Any, 
        ccxt_params: Optional[Dict[str, Any]] = None, 
        provider_for_log: Optional[str] = "unknown_provider" # Changed for consistency
    ) -> Any:
        last_exception: Optional[Exception] = None
        for attempt in range(self.retry_count + 1):
            try:
                if async_fn.__name__ == 'load_markets':
                    reload_flag = ccxt_params.get('reload', False) if ccxt_params else False
                    if reload_flag: 
                         logger.debug(f"Calling {provider_for_log}.load_markets(reload=True)")
                         return await async_fn(reload=True)
                    else:
                         logger.debug(f"Calling {provider_for_log}.load_markets()")
                         return await async_fn() 
                elif ccxt_params: 
                    return await async_fn(*args, params=ccxt_params)
                else:
                    return await async_fn(*args)
            except (ccxt.DDoSProtection, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable, ccxt.NetworkError, ccxt.ExchangeError) as e:
                last_exception = e
                if attempt == self.retry_count:
                    logger.error(f"Max retries for {async_fn.__name__} on {provider_for_log}. Last: {e}", exc_info=True)
                    raise PluginError(f"API call {async_fn.__name__} failed: {e}") from e
                delay = self.retry_delay_base * (2 ** attempt)
                logger.warning(f"{type(e).__name__} on {provider_for_log} (attempt {attempt+1}). Error: {str(e)[:150]}. Retrying in {delay:.2f}s...")
                await asyncio.sleep(delay)
            except ccxt.BadRequest as e:
                logger.error(f"BadRequest for {async_fn.__name__} on {provider_for_log}: {e}", exc_info=True)
                raise PluginError(f"Bad request for {async_fn.__name__}: {e}") from e
            except Exception as e:
                last_exception = e
                logger.error(f"Unexpected error in {async_fn.__name__} (attempt {attempt+1}) for {provider_for_log}: {e}", exc_info=True)
                if attempt == self.retry_count:
                    raise PluginError(f"API call {async_fn.__name__} failed (unexpected): {e}") from e
                delay = self.retry_delay_base * (2 ** attempt)
                await asyncio.sleep(delay)
        if last_exception: raise PluginError(f"Retry loop for {async_fn.__name__} exhausted. Last error: {last_exception}") from last_exception
        raise PluginError(f"Exited retry loop unexpectedly for {async_fn.__name__}.")

    async def get_exchanges(self) -> List[str]: # This returns provider IDs for "crypto" market
        try:
            return sorted(list(ccxt.exchanges))
        except Exception as e:
            raise PluginError(f"Could not load CCXT exchanges list: {e}") from e

    async def get_symbols(self, provider: str) -> List[str]: # CHANGED to provider
        logger.info(f"Fetching symbols for CCXT provider: {provider}")
        try:
            ex = await self._get_exchange_instance(provider) # Use provider as exchange_id for CCXT
            markets = await self._with_retries(ex.load_markets, provider_for_log=provider, ccxt_params=None)
            if not markets: return []
            symbols = [m['symbol'] for m in markets.values() if m.get('active', True) and m.get('spot', True)]
            if not symbols: symbols = [m['symbol'] for m in markets.values() if m.get('active', True)]
            if not symbols: symbols = list(markets.keys())
            return sorted(symbols)
        except PluginError as pe: raise 
        except Exception as e: raise PluginError(f"Error fetching symbols for {provider}: {e}") from e

    async def fetch_historical_ohlcv(
        self, provider: str, symbol: str, timeframe: str, # CHANGED to provider
        since: Optional[int] = None, limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None 
    ) -> List[Dict[str, Any]]:
        ccxt_timeframe = '1m' 
        if timeframe != '1m':
            logger.warning(f"CryptoPlugin.fetch_historical_ohlcv for provider '{provider}' called with timeframe '{timeframe}', "
                           f"but will request '{ccxt_timeframe}' from CCXT.")
        logger.debug(f"Fetching historical OHLCV for {provider}/{symbol} TF={ccxt_timeframe} Since={since} Limit={limit} CCXTParams={params}")
        try:
            ex = await self._get_exchange_instance(provider) # Use provider as exchange_id for CCXT
            if not ex.has.get('fetchOHLCV'):
                raise PluginFeatureNotSupportedError(provider, "fetchOHLCV")
            
            ohlcv_data = await self._with_retries(
                ex.fetch_ohlcv, symbol, ccxt_timeframe, since, limit, 
                ccxt_params=params, 
                provider_for_log=provider # Use provider for logging
            )
            if not ohlcv_data: return []
            
            keys = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            parsed_bars = []
            for bar_list in ohlcv_data:
                if isinstance(bar_list, list) and len(bar_list) >= 6:
                    try:
                        ts = int(bar_list[0])
                        o, h, l_, c = float(bar_list[1]), float(bar_list[2]), float(bar_list[3]), float(bar_list[4])
                        v = float(bar_list[5]) if bar_list[5] is not None else 0.0
                        parsed_bars.append(dict(zip(keys, [ts, o, h, l_, c, v])))
                    except (ValueError, TypeError, IndexError) as e:
                        logger.warning(f"Skipping malformed OHLCV bar from {provider} for {symbol}: {bar_list}, Error: {e}")
                else:
                     logger.warning(f"Skipping non-standard/incomplete OHLCV bar data from {provider} for {symbol}: {bar_list}")
            if parsed_bars: parsed_bars.sort(key=lambda x: x['timestamp'])
            return parsed_bars
        except PluginError as pe: raise
        except Exception as e: raise PluginError(f"Error in fetch_historical_ohlcv for {provider}/{symbol}: {e}") from e

    async def fetch_latest_ohlcv(
        self, provider: str, symbol: str, timeframe: str # CHANGED to provider
    ) -> Optional[Dict[str, Any]]:
        ccxt_timeframe = '1m' 
        if timeframe != '1m':
             logger.warning(f"CryptoPlugin.fetch_latest_ohlcv for provider '{provider}' called with timeframe '{timeframe}',"
                            f" but will request '{ccxt_timeframe}'.")
        logger.debug(f"Fetching latest OHLCV for {provider}/{symbol} TF={ccxt_timeframe}")
        try:
            recent_bars = await self.fetch_historical_ohlcv(
                provider=provider, symbol=symbol, timeframe=ccxt_timeframe, # Use provider here
                limit=LATEST_BAR_LOOKBACK_LIMIT 
            )
            if not recent_bars: return None
            latest_bar = recent_bars[-1] # Already sorted by fetch_historical_ohlcv
            
            current_time_ms = int(time.time() * 1000)
            tf_ms = UNIT_MS.get(ccxt_timeframe[-1]) * int(ccxt_timeframe[:-1]) if ccxt_timeframe[-1] in UNIT_MS and ccxt_timeframe[:-1].isdigit() else 60000
            if latest_bar['timestamp'] < (current_time_ms - tf_ms * (LATEST_BAR_LOOKBACK_LIMIT + 5)):
                logger.warning(f"fetch_latest_ohlcv for {provider}/{symbol}: Latest bar (TS: {latest_bar['timestamp']}) seems stale.")
            return latest_bar
        except PluginError as e: logger.warning(f"PluginError in fetch_latest_ohlcv for {provider}/{symbol}: {e}")
        except Exception as e: logger.error(f"Unexpected error in fetch_latest_ohlcv for {provider}/{symbol}: {e}", exc_info=True)
        return None

    async def watch_ticks(self, provider: str, *args, **kwargs) -> None: 
        raise PluginFeatureNotSupportedError(self.plugin_name, "watch_ticks")
    async def fetch_trades(self, provider: str, *args, **kwargs) -> List[Dict[str, Any]]: 
        raise PluginFeatureNotSupportedError(self.plugin_name, "fetch_trades")
    async def get_trade_client(self, *args, **kwargs) -> Any: # provider context is part of self
        raise PluginFeatureNotSupportedError(self.plugin_name, "get_trade_client")
    async def place_order(self, trade_client: Any, provider: str, *args, **kwargs) -> Dict[str, Any]: 
        raise PluginFeatureNotSupportedError(self.plugin_name, "place_order")
    async def fetch_balance(self, trade_client: Any, provider: str, *args, **kwargs) -> Dict[str, Any]: 
        raise PluginFeatureNotSupportedError(self.plugin_name, "fetch_balance")
    async def fetch_open_orders(self, trade_client: Any, provider: str, *args, **kwargs) -> List[Dict[str, Any]]: 
        raise PluginFeatureNotSupportedError(self.plugin_name, "fetch_open_orders")
    async def get_supported_features(self) -> Dict[str, bool]:
        return { "watch_ticks": False, "fetch_trades": False, "trading_api": False }

    async def close(self):
        logger.info(f"Closing CryptoPlugin and its {len(_exchange_instances)} CCXT instances...")
        tasks = [asyncio.create_task(inst.close(), name=f"CCXT_cleanup_{eid}") 
                 for eid, inst in list(_exchange_instances.items()) 
                 if hasattr(inst, 'close') and asyncio.iscoroutinefunction(inst.close)]
        if tasks: 
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, res in enumerate(results):
                task_name = tasks[i].get_name()
                if isinstance(res, Exception): logger.error(f"Error closing {task_name}: {res}")
                else: logger.info(f"{task_name} closed.")
        _exchange_instances.clear()
        _exchange_access_order.clear()
        logger.info("CryptoPlugin closed and CCXT instances cleared.")