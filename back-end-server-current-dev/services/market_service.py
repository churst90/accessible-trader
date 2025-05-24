# services/market_service.py

import asyncio
import logging
import time
import hashlib
from typing import Any, Dict, List, Optional, Type, Tuple

from quart import Config # For type hinting app_config
# Assuming current_app might be used by dependencies or for global access to Cache/DB_Pool if not directly passed.
# from quart import current_app

from plugins import PluginLoader # The class from plugins/__init__.py
from plugins.base import MarketPlugin, PluginError, OHLCVBar # Import OHLCVBar
from utils.db_utils import DatabaseError, insert_ohlcv_to_db # Added insert_ohlcv_to_db
from services.data_orchestrator import DataOrchestrator
from services.backfill_manager import BackfillManager
from services.cache_manager import Cache as CacheManagerABC # The ABC for cache manager
from services.resampler import Resampler
from services.data_sources.db_source import DbSource # For writing data

logger = logging.getLogger(__name__)

# Default values for plugin instance cache cleanup
DEFAULT_IDLE_PLUGIN_TIMEOUT_SECONDS = 30 * 60  # 30 minutes
DEFAULT_IDLE_CHECK_INTERVAL_SECONDS = 5 * 60   # 5 minutes

class MarketService:
    """
    Central service for accessing market data.

    Responsibilities:
    - Manages the lifecycle of market data plugin instances (creation, caching, cleanup).
    - Uses PluginLoader to dynamically find and load appropriate plugin classes.
    - Provides methods to fetch symbols, OHLCV data, and trigger backfills,
      typically by orchestrating calls to DataOrchestrator or specific plugin instances.
    - Handles user-specific API credentials for plugin instantiation (conceptually).
    """

    _resampler_instance: Optional[Resampler] = None
    # _plugin_loader_instance: Optional[PluginLoader] = None # PluginLoader is class-based
    _db_source_instance: Optional[DbSource] = None # Shared instance for writes

    def __init__(self, app_config: Config):
        """
        Initializes the MarketService.

        Args:
            app_config (Config): The Quart application configuration object.
                                   Used for accessing settings like timeouts, cache, DB pool.
        """
        self._app_config = app_config
        self.plugin_instances_cache: Dict[tuple, Tuple[MarketPlugin, float]] = {}
        self.plugin_cache_lock = asyncio.Lock()

        self.idle_plugin_timeout_seconds: int = int(self._app_config.get(
            "IDLE_PLUGIN_TIMEOUT_SECONDS", DEFAULT_IDLE_PLUGIN_TIMEOUT_SECONDS
        ))
        self.idle_check_interval_seconds: int = int(self._app_config.get(
            "IDLE_CHECK_INTERVAL_SECONDS", DEFAULT_IDLE_CHECK_INTERVAL_SECONDS
        ))
        self._periodic_cleanup_task: Optional[asyncio.Task] = None

        # Initialize shared, stateless components or loaders if not already done by a previous instance
        # (though typically MarketService itself is a singleton in the app).
        # PluginLoader uses class methods, discover_plugins called on first use if needed.
        if not PluginLoader.list_plugins(): # Ensures discovery has run
            logger.info("MarketService: Triggering PluginLoader discovery during MarketService init.")
            PluginLoader.discover_plugins()
        
        if MarketService._resampler_instance is None:
            MarketService._resampler_instance = Resampler()
            logger.info("MarketService: Global Resampler initialized/accessed.")

        if MarketService._db_source_instance is None:
            # DbSource is fairly stateless for writes, can be shared.
            MarketService._db_source_instance = DbSource( # Generic instance for writes
                market=None, provider=None, symbol=None 
            )
            logger.info("MarketService: Shared DbSource instance for writes initialized/accessed.")

        logger.info(
            f"MarketService initialized. Plugin Idle Timeout: {self.idle_plugin_timeout_seconds}s, "
            f"Cleanup Check Interval: {self.idle_check_interval_seconds}s."
        )

    async def _get_user_api_credentials(self, user_id: Optional[str], plugin_target_provider: str) -> Dict[str, Optional[str]]:
        """
        Placeholder for fetching user-specific API credentials.
        In a real application, this would query a secure database or secrets manager.

        Args:
            user_id (Optional[str]): The ID of the user.
            plugin_target_provider (str): The specific provider the credentials are for (e.g., "binance", "alpaca").

        Returns:
            Dict[str, Optional[str]]: A dict with 'api_key', 'api_secret', 'api_passphrase'.
                                         Values are None if no specific keys found for the user/provider.
        """
        # TODO: Implement actual secure credential lookup from user_configs database
        # For now, this always returns None, meaning plugins will use public access
        # or fall back to environment variables if they are designed to do so.
        if user_id:
            logger.debug(f"MarketService: Placeholder: Attempting to fetch API credentials for user '{user_id}', provider '{plugin_target_provider}'. Returning no keys.")
        return {'api_key': None, 'api_secret': None, 'api_passphrase': None}

    def _generate_plugin_cache_key(
        self,
        plugin_class_key: str,      # e.g., "crypto", "alpaca"
        provider_id_for_instance: str, # e.g., "binance", "kraken", "alpaca"
        api_key_public_hash: Optional[str], # A hash of the API key, or a standard string for public access
        is_testnet: bool
    ) -> tuple:
        """
        Generates a unique cache key for a plugin instance configuration.
        """
        # Normalize for cache key stability
        normalized_plugin_class_key = plugin_class_key.lower().strip()
        normalized_provider_id = provider_id_for_instance.lower().strip()
        key_identifier = api_key_public_hash if api_key_public_hash else "public_access"
        
        return (normalized_plugin_class_key, normalized_provider_id, key_identifier, is_testnet)

    async def get_plugin_instance(
        self,
        market: str, # The requested market (e.g., "crypto", "stocks", "us_equity")
        provider: str, # The specific provider for that market (e.g., "binance", "alpaca", "polygon")
        user_id: Optional[str] = None, 
        api_credentials_override: Optional[Dict[str, Optional[str]]] = None, 
        is_testnet_override: Optional[bool] = None 
    ) -> MarketPlugin:
        if not market or not provider:
            raise ValueError("Market and provider must be specified to get a plugin instance.")

        # Step 1: Get all plugin keys that claim to support the given 'market'
        plugin_class_keys_for_market: List[str] = PluginLoader.get_plugin_keys_for_market(market)
        
        if not plugin_class_keys_for_market:
            msg = f"No plugin classes are registered to handle the market '{market}'."
            logger.error(f"MarketService: {msg}")
            raise ValueError(msg)

        # Step 2: Find the specific plugin class (among those supporting the market) 
        # that can be configured for the requested 'provider'.
        target_plugin_class: Optional[Type[MarketPlugin]] = None
        target_plugin_class_key: Optional[str] = None

        for p_key in plugin_class_keys_for_market:
            p_class = PluginLoader.get_plugin_class_by_key(p_key)
            if p_class:
                # list_configurable_providers() should return names like "binance", "alpaca", "polygon"
                # which are the actual provider IDs the plugin instance will be configured with.
                configurable_providers = p_class.list_configurable_providers()
                if provider.lower() in [prov.lower() for prov in configurable_providers]:
                    target_plugin_class = p_class
                    target_plugin_class_key = p_key
                    logger.debug(f"MarketService: For market '{market}' and provider '{provider}', "
                                 f"found matching plugin class '{p_class.__name__}' with key '{p_key}'.")
                    break # Found the correct plugin class
        
        if not target_plugin_class or not target_plugin_class_key:
            # This means that although some plugins might support the 'market', 
            # none of them list the specific 'provider' as one they can be configured for.
            msg = (f"No plugin found that supports market '{market}' AND can be configured for provider '{provider}'. "
                   f"Plugins supporting market '{market}': {plugin_class_keys_for_market}. "
                   f"Please check plugin configurations and ensure the provider name ('{provider}') "
                   f"is listed in the chosen plugin's list_configurable_providers().")
            logger.error(f"MarketService: {msg}")
            raise ValueError(msg)
        
        # Use the resolved target_plugin_class and target_plugin_class_key
        plugin_class = target_plugin_class 
        plugin_class_key = target_plugin_class_key
        
        logger.debug(f"MarketService: For market '{market}', provider '{provider}', determined plugin class key to load: '{plugin_class_key}'.")

        # Step 3: Determine API credentials and testnet status
        is_testnet = is_testnet_override if is_testnet_override is not None \
                         else self._app_config.get('ENV') == 'testing'
        
        creds_to_use: Dict[str, Optional[str]]
        if api_credentials_override is not None:
            creds_to_use = api_credentials_override
        elif user_id:
            creds_to_use = await self._get_user_api_credentials(user_id, provider.lower())
        else: 
            creds_to_use = {'api_key': None, 'api_secret': None, 'api_passphrase': None}

        api_key_for_hash = creds_to_use.get('api_key')
        api_key_identifier = hashlib.sha256(api_key_for_hash.encode('utf-8')).hexdigest() if api_key_for_hash else "public_access"

        # Step 4: Generate cache key and check instance cache
        instance_cache_key = self._generate_plugin_cache_key(
            plugin_class_key, provider.lower(), api_key_identifier, is_testnet
        )
        logger.debug(f"MarketService: Instance cache key for plugin: {instance_cache_key}")

        async with self.plugin_cache_lock:
            cached_entry = self.plugin_instances_cache.get(instance_cache_key)
            if cached_entry:
                plugin_instance_cached, _ = cached_entry
                self.plugin_instances_cache[instance_cache_key] = (plugin_instance_cached, time.monotonic())
                logger.debug(f"MarketService: Reusing cached plugin instance for key {instance_cache_key}")
                return plugin_instance_cached

            # Step 5: Instantiate and cache if not found
            logger.info(f"MarketService: Creating new plugin instance for {instance_cache_key} (Class: {plugin_class.__name__}, Provider ID for instance: {provider.lower()})")
            try:
                plugin_instance = plugin_class(
                    provider_id=provider.lower(), # This is the crucial provider_id for the instance
                    api_key=creds_to_use.get('api_key'),
                    api_secret=creds_to_use.get('api_secret'),
                    api_passphrase=creds_to_use.get('api_passphrase'),
                    is_testnet=is_testnet,
                    request_timeout=int(self._app_config.get('PLUGIN_REQUEST_TIMEOUT_MS', 30000)),
                    verbose_logging=bool(self._app_config.get('PLUGIN_VERBOSE_LOGGING', False))
                )
                self.plugin_instances_cache[instance_cache_key] = (plugin_instance, time.monotonic())
                logger.info(f"MarketService: Successfully created and cached new plugin instance for {instance_cache_key}.")
                return plugin_instance
            except Exception as e:
                logger.error(
                    f"MarketService: Failed to instantiate plugin class '{plugin_class.__name__}' "
                    f"(key '{plugin_class_key}') for provider_id '{provider.lower()}': {e}", exc_info=True
                )
                raise PluginError(
                    message=f"Failed to initialize plugin '{plugin_class_key}' for provider '{provider.lower()}'. Original: {type(e).__name__}: {str(e)}",
                    provider_id=provider.lower(),
                    original_exception=e
                ) from e

    async def _run_periodic_idle_check(self):
        while True:
            await asyncio.sleep(self.idle_check_interval_seconds)
            logger.debug(f"MarketService: Running periodic idle plugin check (Timeout: {self.idle_plugin_timeout_seconds}s)...")
            try:
                keys_to_remove_and_close: List[Tuple[tuple, MarketPlugin]] = []
                current_time = time.monotonic()
                
                async with self.plugin_cache_lock: 
                    keys_for_removal_pass = []
                    for key, (instance, last_accessed) in self.plugin_instances_cache.items():
                        if current_time - last_accessed > self.idle_plugin_timeout_seconds:
                            keys_for_removal_pass.append(key)
                            keys_to_remove_and_close.append((key, instance)) 
                    
                    for key_to_remove in keys_for_removal_pass:
                        if key_to_remove in self.plugin_instances_cache: 
                           del self.plugin_instances_cache[key_to_remove]
                
                for key_removed, instance_to_close in keys_to_remove_and_close:
                    logger.info(f"MarketService: Closing idle plugin instance (key: {key_removed}).Provider: {instance_to_close.provider_id}")
                    try:
                        await instance_to_close.close()
                    except Exception as e_close:
                        logger.error(f"MarketService: Error closing idle plugin (key: {key_removed}): {e_close}", exc_info=True)
                
                if keys_to_remove_and_close:
                    logger.info(f"MarketService: Closed {len(keys_to_remove_and_close)} idle plugin instances.")
                else:
                    logger.debug("MarketService: No idle plugin instances found to close.")
            except asyncio.CancelledError:
                logger.info("MarketService: Periodic idle plugin check task cancelled.")
                break
            except Exception as e_check:
                logger.error(f"MarketService: Error in _run_periodic_idle_check loop: {e_check}", exc_info=True)


    async def start_periodic_cleanup(self):
        if self._periodic_cleanup_task is None or self._periodic_cleanup_task.done():
            self._periodic_cleanup_task = asyncio.create_task(self._run_periodic_idle_check(), name="MarketServiceIdlePluginCleanup")
            logger.info(f"MarketService: Started periodic idle plugin cleanup task (Interval: {self.idle_check_interval_seconds}s).")
        else:
            logger.debug("MarketService: Periodic idle plugin cleanup task already running.")

    async def _cleanup_all_cached_plugins(self):
        logger.info(f"MarketService: Closing all {len(self.plugin_instances_cache)} cached plugin instances...")
        instances_to_close: List[MarketPlugin] = []
        async with self.plugin_cache_lock:
            for _key, (instance, _last_accessed) in list(self.plugin_instances_cache.items()):
                instances_to_close.append(instance)
            self.plugin_instances_cache.clear()
        for instance in instances_to_close:
            provider_info = instance.provider_id if hasattr(instance, 'provider_id') else 'unknown_provider'
            logger.debug(f"MarketService: Closing plugin for provider '{provider_info}' during full cleanup.")
            try:
                await instance.close()
            except Exception as e_close:
                logger.error(f"MarketService: Error closing plugin for '{provider_info}': {e_close}", exc_info=True)
        logger.info("MarketService: All cached plugins processed for closure.")

    async def app_shutdown_cleanup(self):
        logger.info("MarketService: Initiating shutdown cleanup...")
        if self._periodic_cleanup_task and not self._periodic_cleanup_task.done():
            logger.info("MarketService: Cancelling periodic idle check task...")
            self._periodic_cleanup_task.cancel()
            try:
                await self._periodic_cleanup_task
            except asyncio.CancelledError:
                logger.info("MarketService: Periodic idle check task successfully cancelled.")
            except Exception as e_await_cancel:
                logger.error(f"MarketService: Error encountered while awaiting cancelled periodic task: {e_await_cancel}", exc_info=True)
        self._periodic_cleanup_task = None
        await self._cleanup_all_cached_plugins()
        logger.info("MarketService: Application shutdown cleanup complete.")

    async def fetch_ohlcv(
        self, market: str, provider: str, symbol: str, timeframe: str,
        since: Optional[int] = None, until: Optional[int] = None, 
        limit: Optional[int] = None, user_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> List[OHLCVBar]:
        if not all([market, provider, symbol, timeframe]):
            raise ValueError("Market, provider, symbol, and timeframe are required for fetch_ohlcv.")
        log_key = f"{market}:{provider}:{symbol}@{timeframe}"
        logger.debug(f"MarketService: Requesting fetch_ohlcv for {log_key}, User: {user_id}, Since: {since}, Until: {until}, Limit: {limit}")

        cache_manager: Optional[CacheManagerABC] = self._app_config.get("CACHE")
        db_source_instance: Optional[DbSource] = MarketService._db_source_instance
        resampler_instance: Optional[Resampler] = MarketService._resampler_instance

        if not db_source_instance:
            logger.critical("MarketService: Shared DbSource instance not initialized!")
            raise RuntimeError("DbSource not available for DataOrchestrator.")
        if not resampler_instance:
            logger.critical("MarketService: Global Resampler instance not initialized!")
            raise RuntimeError("Resampler not available for DataOrchestrator.")
        if not cache_manager and self._app_config.get("CACHE_ENABLED", False):
            logger.error("MarketService: Cache (CACHE_MANAGER) not found in app.config but CACHE_ENABLED is true.")
            raise RuntimeError("Cache misconfiguration: CACHE_ENABLED is true but no cache manager found.")

        orchestrator = DataOrchestrator(
            app_context=self._app_config,
            market_service=self,
            redis_cache_manager=cache_manager, 
            db_source=db_source_instance,
            resampler=resampler_instance
        )
        try:
            bars: List[OHLCVBar] = await orchestrator.fetch_ohlcv(
                market=market, provider=provider, symbol=symbol,
                requested_timeframe=timeframe, 
                since=since, limit=limit, until=until,
                params=params, 
                user_id_for_plugin=user_id, 
                is_backfill=False 
            )
            logger.info(f"MarketService: DataOrchestrator returned {len(bars)} bars for {log_key}.")
            return bars
        except PluginError: raise
        except Exception as e_fetch:
            logger.error(f"MarketService: Error from DataOrchestrator for {log_key}: {e_fetch}", exc_info=True)
            raise RuntimeError(f"Data fetch failed for {log_key}: {e_fetch}") from e_fetch

    async def get_symbols(self, market: str, provider: str, user_id: Optional[str] = None) -> List[str]:
        logger.debug(f"MarketService: Getting symbols for market '{market}', provider '{provider}', User: {user_id}")
        try:
            plugin_instance = await self.get_plugin_instance(market, provider, user_id=user_id)
            symbols = await plugin_instance.get_symbols(market=market) # Ensure 'market' is passed here
            logger.info(f"MarketService: Fetched {len(symbols)} symbols for {market}/{provider} via {plugin_instance.__class__.__name__}.")
            return symbols
        except PluginError: raise
        except ValueError as ve:
            logger.error(f"MarketService: ValueError in get_symbols for {market}/{provider}: {ve}", exc_info=False) 
            raise
        except Exception as e:
            logger.error(f"MarketService: Unexpected error in get_symbols for {market}/{provider}: {e}", exc_info=True)
            raise RuntimeError(f"Unexpected error fetching symbols for {market}/{provider}: {e}") from e

    async def fetch_latest_bar(
        self, market: str, provider: str, symbol: str, timeframe: str = "1m", user_id: Optional[str] = None
    ) -> Optional[OHLCVBar]:
        if not symbol: raise ValueError("Symbol must be provided for fetch_latest_bar.")
        logger.debug(f"MarketService: Fetching latest '{timeframe}' bar for {market}/{provider}/{symbol}, User: {user_id}")
        try:
            plugin_instance = await self.get_plugin_instance(market, provider, user_id=user_id)
            latest_bar = await plugin_instance.fetch_latest_ohlcv(symbol=symbol, timeframe=timeframe)
            if latest_bar:
                logger.info(f"MarketService: Fetched latest '{timeframe}' bar for {symbol} @ {latest_bar['timestamp']}.")
                asyncio.create_task(
                    self.save_recent_bars_to_db_and_cache(market, provider, symbol, timeframe, [latest_bar]),
                    name=f"SaveLatestBar_{market}_{provider}_{symbol}"
                )
                return latest_bar
            logger.warning(f"MarketService: No latest '{timeframe}' bar returned by plugin for {symbol}.")
            return None
        except PluginError as e:
            logger.error(f"MarketService: PluginError fetching latest bar for {symbol}: {e}", exc_info=False)
            return None 
        except Exception as e:
            logger.error(f"MarketService: Unexpected error fetching latest bar for {symbol}: {e}", exc_info=True)
            return None

    async def save_recent_bars_to_db_and_cache(
        self, market: str, provider: str, symbol: str, timeframe: str, bars: List[OHLCVBar],
    ):
        if not all([market, provider, symbol, timeframe]) or not bars :
            logger.warning(f"MarketService (save_recent_bars): Insufficient data provided (Market: {market}, Provider: {provider}, Symbol: {symbol}, TF: {timeframe}, Bars count: {len(bars) if bars else 0}). Skipping save.")
            return
        log_key = f"{market}:{provider}:{symbol}@{timeframe}"
        logger.info(f"MarketService: Saving {len(bars)} bars for {log_key} to DB/Cache.")
        db_s = MarketService._db_source_instance
        if not db_s: 
            logger.critical("MarketService (save_recent_bars): Shared DbSource instance not available!")
            return
        cache_mgr: Optional[CacheManagerABC] = self._app_config.get("CACHE")
        dict_bars = [dict(b) for b in bars] 
        try:
            await insert_ohlcv_to_db(market, provider, symbol, timeframe, dict_bars)
            logger.debug(f"MarketService: DB save completed for {len(bars)} bars of {log_key}.")
        except DatabaseError as dbe:
            logger.error(f"MarketService: DatabaseError during DB save for {log_key}: {dbe}", exc_info=True)
        except Exception as e_db_task:
            logger.error(f"MarketService: Error during DB save for {log_key}: {e_db_task}", exc_info=True)

        if cache_mgr and self._app_config.get("CACHE_ENABLED", False):
            try:
                if timeframe == "1m": 
                    await cache_mgr.store_1m_bars(market, provider, symbol, dict_bars)
                    logger.debug(f"MarketService: 1m Cache save completed for {len(bars)} bars of {log_key}.")
            except Exception as e_cache_task:
                logger.error(f"MarketService: Error during cache save for {log_key}: {e_cache_task}", exc_info=True)
    
    async def trigger_historical_backfill_if_needed(
        self, market: str, provider: str, symbol: str, 
        timeframe_context: str, user_id: Optional[str] = None
    ):
        if not symbol: raise ValueError("Symbol is required for backfill trigger.")
        log_key = f"{market}:{provider}:{symbol}"
        logger.info(f"MarketService: Backfill trigger requested for {log_key} (Context TF: {timeframe_context}), User: {user_id}")
        try:
            plugin_instance = await self.get_plugin_instance(market, provider, user_id=user_id)
            cache_mgr: Optional[CacheManagerABC] = self._app_config.get("CACHE")
            db_pool = self._app_config.get("DB_POOL")
            if not db_pool:
                logger.error(f"MarketService: DB_POOL not available in app_config for BackfillManager for {log_key}.")
                return

            backfill_manager = BackfillManager(
                market=market, provider=provider, symbol=symbol,
                plugin=plugin_instance, 
                cache=cache_mgr
            )
            asyncio.create_task(
                backfill_manager.trigger_historical_backfill_if_needed(timeframe_context=timeframe_context), 
                name=f"DispatchBackfillTrigger_{log_key}"
            )
            logger.info(f"MarketService: Backfill trigger task dispatched for {log_key} via BackfillManager.")
        except PluginError as e_plugin:
            logger.error(f"MarketService: PluginError during backfill trigger setup for {log_key}: {e_plugin}", exc_info=True)
        except Exception as e_setup:
            logger.error(f"MarketService: Unexpected error during backfill trigger setup for {log_key}: {e_setup}", exc_info=True)