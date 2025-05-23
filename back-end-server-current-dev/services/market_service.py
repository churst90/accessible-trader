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
from plugins.base import MarketPlugin, PluginError, OHLCVBar
from utils.db_utils import DatabaseError # For save_recent_bars...
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
    _plugin_loader_instance: Optional[PluginLoader] = None
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
        if MarketService._plugin_loader_instance is None:
            MarketService._plugin_loader_instance = PluginLoader()
            logger.info("MarketService: Global PluginLoader initialized/accessed.")
            # Ensure discovery runs if it hasn't (PluginLoader might auto-discover on first use)
            if not MarketService._plugin_loader_instance.list_plugins():
                 MarketService._plugin_loader_instance.discover_plugins()
        
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

        Args:
            plugin_class_key (str): The key of the plugin class (e.g., "crypto").
            provider_id_for_instance (str): The specific provider this instance handles (e.g., "binance").
            api_key_public_hash (Optional[str]): A hash of the API key for keyed instances,
                                               or a specific marker like "public_access" for non-keyed.
            is_testnet (bool): Testnet status.

        Returns:
            tuple: A unique tuple to be used as a dictionary key.
        """
        # Normalize for cache key stability
        normalized_plugin_class_key = plugin_class_key.lower().strip()
        normalized_provider_id = provider_id_for_instance.lower().strip()
        key_identifier = api_key_public_hash if api_key_public_hash else "public_access"
        
        return (normalized_plugin_class_key, normalized_provider_id, key_identifier, is_testnet)

    async def get_plugin_instance(
        self,
        market: str, # The requested market (e.g., "crypto", "stocks")
        provider: str, # The specific provider for that market (e.g., "binance", "alpaca")
        user_id: Optional[str] = None, # For fetching user-specific API keys
        api_credentials_override: Optional[Dict[str, Optional[str]]] = None, # To directly pass keys
        is_testnet_override: Optional[bool] = None # To override app's default testnet status
    ) -> MarketPlugin:
        """
        Gets or creates a cached MarketPlugin instance configured for the specified
        market, provider, user credentials, and testnet status.

        Args:
            market (str): The market type (e.g., "crypto", "stocks").
            provider (str): The specific data provider ID (e.g., "binance", "alpaca").
            user_id (Optional[str]): User ID to fetch API credentials for.
            api_credentials_override (Optional[Dict[str, Optional[str]]]):
                If provided, these credentials are used instead of fetching by user_id.
            is_testnet_override (Optional[bool]): Explicitly set testnet mode for this instance.
                                                 If None, uses app default (ENV=testing).

        Returns:
            MarketPlugin: A configured and potentially cached plugin instance.

        Raises:
            ValueError: If market/provider is invalid or no suitable plugin class is found.
            PluginError: If plugin instantiation fails.
        """
        if not market or not provider:
            raise ValueError("Market and provider must be specified to get a plugin instance.")

        if MarketService._plugin_loader_instance is None:
            logger.critical("MarketService.get_plugin_instance: PluginLoader is not initialized!")
            raise RuntimeError("PluginLoader not initialized. Cannot get plugin instance.")

        # 1. Determine the plugin_key of the CLASS that handles this market
        plugin_class_key = MarketService._plugin_loader_instance.get_plugin_key_for_market(market)

        if not plugin_class_key:
            # Fallback: If the provider name itself is a registered plugin_key
            # (e.g., market="any_market", provider="alpaca", and "alpaca" is a plugin_key)
            if provider.lower() in MarketService._plugin_loader_instance.list_plugins():
                plugin_class_key = provider.lower()
                logger.info(f"MarketService: No direct plugin for market '{market}'. Using provider '{provider}' as plugin class key: '{plugin_class_key}'.")
            else:
                available_keys = MarketService._plugin_loader_instance.list_plugins()
                msg = f"No plugin class registered for market '{market}', and provider '{provider}' is not a direct plugin key. Available plugin keys: {available_keys}"
                logger.error(f"MarketService: {msg}")
                raise ValueError(msg)
        
        logger.debug(f"MarketService: For market '{market}', provider '{provider}', determined plugin class key to load: '{plugin_class_key}'.")

        # 2. Load the Plugin Class
        plugin_class = MarketService._plugin_loader_instance.get_plugin_class_by_key(plugin_class_key)
        if not plugin_class:
            msg = f"Failed to load plugin class for key '{plugin_class_key}' (for market '{market}')."
            logger.critical(f"MarketService: {msg}")
            raise ValueError(msg)

        # 3. Validate if this plugin class can handle the specific provider
        configurable_providers = plugin_class.list_configurable_providers()
        if provider.lower() not in [p.lower() for p in configurable_providers]:
            msg = (f"Plugin class '{plugin_class.__name__}' (key: {plugin_class_key}) "
                   f"does not support configuring for provider '{provider}'. "
                   f"Supported by this class: {configurable_providers}")
            logger.error(f"MarketService: {msg}")
            raise ValueError(msg)
            
        # 4. Determine API credentials and testnet status
        is_testnet = is_testnet_override if is_testnet_override is not None \
                     else self._app_config.get('ENV') == 'testing'
        
        creds_to_use: Dict[str, Optional[str]]
        if api_credentials_override is not None:
            creds_to_use = api_credentials_override
        elif user_id:
            creds_to_use = await self._get_user_api_credentials(user_id, provider.lower())
        else: # Public access or plugin relies on env vars
            creds_to_use = {'api_key': None, 'api_secret': None, 'api_passphrase': None}

        # Generate a public hash of the API key for the cache key to differentiate user instances
        # without storing the actual key in the cache key if it's sensitive.
        api_key_for_hash = creds_to_use.get('api_key')
        api_key_identifier = hashlib.sha256(api_key_for_hash.encode('utf-8')).hexdigest() if api_key_for_hash else "public_access"

        # 5. Generate cache key and check instance cache
        # The provider_id_for_instance is the specific exchange/provider this instance will handle.
        instance_cache_key = self._generate_plugin_cache_key(
            plugin_class_key, provider.lower(), api_key_identifier, is_testnet
        )
        logger.debug(f"MarketService: Instance cache key for plugin: {instance_cache_key}")

        async with self.plugin_cache_lock:
            cached_entry = self.plugin_instances_cache.get(instance_cache_key)
            if cached_entry:
                plugin_instance, _ = cached_entry
                self.plugin_instances_cache[instance_cache_key] = (plugin_instance, time.monotonic()) # Update last access time
                logger.debug(f"MarketService: Reusing cached plugin instance for key {instance_cache_key}")
                return plugin_instance

            # 6. Instantiate and cache if not found
            logger.info(f"MarketService: Creating new plugin instance for {instance_cache_key} (Class: {plugin_class.__name__}, Provider ID for instance: {provider.lower()})")
            try:
                # When instantiating, provider_id is the specific provider for this instance.
                plugin_instance = plugin_class(
                    provider_id=provider.lower(), # Critical: this is the specific CCXT id or "alpaca"
                    api_key=creds_to_use.get('api_key'),
                    api_secret=creds_to_use.get('api_secret'),
                    api_passphrase=creds_to_use.get('api_passphrase'),
                    is_testnet=is_testnet,
                    request_timeout=int(self._app_config.get('CCXT_REQUEST_TIMEOUT_MS', 30000)), # Example specific config
                    verbose_logging=bool(self._app_config.get('PLUGIN_VERBOSE_LOGGING', False))
                    # Pass other relevant general configs from app_config if plugins need them
                )
                self.plugin_instances_cache[instance_cache_key] = (plugin_instance, time.monotonic())
                logger.info(f"MarketService: Successfully created and cached new plugin instance for {instance_cache_key}.")
                return plugin_instance
            except Exception as e:
                logger.error(
                    f"MarketService: Failed to instantiate plugin class '{plugin_class.__name__}' "
                    f"(key '{plugin_class_key}') for provider_id '{provider.lower()}': {e}", exc_info=True
                )
                # Wrap in PluginError for consistent error handling upstream
                raise PluginError(
                    message=f"Failed to initialize plugin '{plugin_class_key}' for provider '{provider.lower()}'. Original: {type(e).__name__}: {str(e)}",
                    provider_id=provider.lower(),
                    original_exception=e
                ) from e

    # --- Idle Plugin Cleanup Methods ---
    async def _run_periodic_idle_check(self):
        """Periodically checks for idle plugin instances and closes them."""
        while True:
            await asyncio.sleep(self.idle_check_interval_seconds)
            logger.debug(f"MarketService: Running periodic idle plugin check (Timeout: {self.idle_plugin_timeout_seconds}s)...")
            try:
                keys_to_remove_and_close: List[Tuple[tuple, MarketPlugin]] = []
                current_time = time.monotonic()
                
                async with self.plugin_cache_lock: # Lock while iterating and preparing removal list
                    # Iterate over a copy of items if modifying the dict, or build a list of keys to remove
                    keys_for_removal_pass = []
                    for key, (instance, last_accessed) in self.plugin_instances_cache.items():
                        if current_time - last_accessed > self.idle_plugin_timeout_seconds:
                            keys_for_removal_pass.append(key)
                            keys_to_remove_and_close.append((key, instance)) # Store instance for closing outside lock
                    
                    for key_to_remove in keys_for_removal_pass:
                        if key_to_remove in self.plugin_instances_cache: # Check again before deleting
                           del self.plugin_instances_cache[key_to_remove]
                
                # Close instances outside the lock to avoid holding lock during awaitable close()
                for key_removed, instance_to_close in keys_to_remove_and_close:
                    logger.info(f"MarketService: Closing idle plugin instance (key: {key_removed})...")
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
        """Starts the background task for cleaning up idle plugin instances."""
        if self._periodic_cleanup_task is None or self._periodic_cleanup_task.done():
            self._periodic_cleanup_task = asyncio.create_task(self._run_periodic_idle_check(), name="MarketServiceIdlePluginCleanup")
            logger.info(f"MarketService: Started periodic idle plugin cleanup task (Interval: {self.idle_check_interval_seconds}s).")
        else:
            logger.debug("MarketService: Periodic idle plugin cleanup task already running.")

    async def _cleanup_all_cached_plugins(self):
        """Closes all currently cached plugin instances. Typically used during shutdown."""
        logger.info(f"MarketService: Closing all {len(self.plugin_instances_cache)} cached plugin instances...")
        
        instances_to_close: List[MarketPlugin] = []
        async with self.plugin_cache_lock:
            for key, (instance, _) in list(self.plugin_instances_cache.items()): # list() for safe iteration if modifying
                instances_to_close.append(instance)
            self.plugin_instances_cache.clear() # Clear the cache

        for instance in instances_to_close:
            provider_info = instance.provider_id if hasattr(instance, 'provider_id') else 'unknown_provider'
            logger.debug(f"MarketService: Closing plugin for provider '{provider_info}' during full cleanup.")
            try:
                await instance.close()
            except Exception as e_close:
                logger.error(f"MarketService: Error closing plugin for '{provider_info}': {e_close}", exc_info=True)
        logger.info("MarketService: All cached plugins processed for closure.")


    async def app_shutdown_cleanup(self):
        """Performs cleanup actions when the application is shutting down."""
        logger.info("MarketService: Initiating shutdown cleanup...")
        if self._periodic_cleanup_task and not self._periodic_cleanup_task.done():
            logger.info("MarketService: Cancelling periodic idle check task...")
            self._periodic_cleanup_task.cancel()
            try:
                await self._periodic_cleanup_task
            except asyncio.CancelledError:
                logger.info("MarketService: Periodic idle check task successfully cancelled.")
            except Exception as e_await_cancel: # Should not happen often
                logger.error(f"MarketService: Error encountered while awaiting cancelled periodic task: {e_await_cancel}", exc_info=True)
        self._periodic_cleanup_task = None
        
        await self._cleanup_all_cached_plugins()
        logger.info("MarketService: Application shutdown cleanup complete.")

    # --- Public Data Access Methods ---

    async def fetch_ohlcv(
        self, market: str, provider: str, symbol: str, timeframe: str,
        since: Optional[int] = None, until: Optional[int] = None, 
        limit: Optional[int] = None, user_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None # For plugin-specific passthrough
    ) -> List[OHLCVBar]:
        """
        Fetches OHLCV data, orchestrating through DataOrchestrator.

        Args:
            market (str): Market identifier (e.g., "crypto", "stocks").
            provider (str): Provider identifier (e.g., "binance", "alpaca").
            symbol (str): Trading symbol (e.g., "BTC/USDT", "AAPL").
            timeframe (str): Timeframe string (e.g., "1m", "1D").
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            until (Optional[int]): End timestamp in milliseconds (exclusive).
            limit (Optional[int]): Maximum number of bars.
            user_id (Optional[str]): ID of the user making the request, for API key retrieval.
            params (Optional[Dict[str, Any]]): Additional parameters for the plugin.

        Returns:
            List[OHLCVBar]: A list of OHLCV bars.
        
        Raises:
            ValueError: If required parameters are missing or invalid.
            RuntimeError: If essential services (Cache, DB, Resampler) are not configured.
            PluginError: If issues arise from the underlying plugin.
        """
        if not all([market, provider, symbol, timeframe]):
            raise ValueError("Market, provider, symbol, and timeframe are required for fetch_ohlcv.")

        log_key = f"{market}:{provider}:{symbol}@{timeframe}"
        logger.debug(f"MarketService: Requesting fetch_ohlcv for {log_key}, User: {user_id}, Since: {since}, Until: {until}, Limit: {limit}")

        # Ensure shared components are available
        cache_manager: Optional[CacheManagerABC] = self._app_config.get("CACHE")
        db_source_instance: Optional[DbSource] = MarketService._db_source_instance
        resampler_instance: Optional[Resampler] = MarketService._resampler_instance

        if not cache_manager: # Assuming cache_manager might be optional for some setups
            logger.warning("MarketService: CacheManager (CACHE) not found in app.config. Proceeding without it if orchestrator allows.")
        if not db_source_instance:
            logger.error("MarketService: Shared DbSource instance not initialized!")
            raise RuntimeError("DbSource not available for DataOrchestrator.")
        if not resampler_instance:
            logger.error("MarketService: Global Resampler instance not initialized!")
            raise RuntimeError("Resampler not available for DataOrchestrator.")

        # DataOrchestrator needs the MarketService instance to get plugins
        orchestrator = DataOrchestrator(
            app_context=self._app_config, # Pass app_config or current_app
            market_service=self,
            redis_cache_manager=cache_manager, # Can be None if cache is optional
            db_source=db_source_instance,
            resampler=resampler_instance
        )
        
        try:
            # DataOrchestrator is responsible for the complex fetching logic
            # including deciding when to use aggregates, cache, or plugins.
            bars: List[OHLCVBar] = await orchestrator.fetch_ohlcv(
                market=market, provider=provider, symbol=symbol,
                requested_timeframe=timeframe, # Pass the originally requested timeframe
                since=since, limit=limit, until=until,
                params=params, # Pass through extra params
                user_id_for_plugin=user_id, # For orchestrator to get correct plugin if needed
                is_backfill=False 
            )
            logger.info(f"MarketService: DataOrchestrator returned {len(bars)} bars for {log_key}.")
            # Note: Formatting for Highcharts (if needed) should now happen in the blueprint.
            return bars
        except PluginError: # Re-raise plugin errors to be handled by blueprint
            raise
        except Exception as e_fetch:
            logger.error(f"MarketService: Error from DataOrchestrator for {log_key}: {e_fetch}", exc_info=True)
            # Wrap in a generic runtime error or a more specific MarketServiceError if defined
            raise RuntimeError(f"Data fetch failed for {log_key}: {e_fetch}") from e_fetch

    async def get_symbols(self, market: str, provider: str, user_id: Optional[str] = None) -> List[str]:
        """
        Retrieves tradable symbols for the given market and provider.

        Args:
            market (str): The market identifier.
            provider (str): The provider identifier.
            user_id (Optional[str]): User ID for context if credentials are required for symbol listing.

        Returns:
            List[str]: A list of tradable symbols.
        """
        logger.debug(f"MarketService: Getting symbols for {market}/{provider}, User: {user_id}")
        try:
            # Get plugin instance (public access if no user_id or no keys for user)
            plugin_instance = await self.get_plugin_instance(market, provider, user_id=user_id)
            
            symbols = await plugin_instance.get_symbols()
            logger.info(f"MarketService: Fetched {len(symbols)} symbols for {market}/{provider} via {plugin_instance.__class__.__name__}.")
            return symbols
        except PluginError: # Re-raise plugin errors
            raise
        except Exception as e:
            logger.error(f"MarketService: Unexpected error in get_symbols for {market}/{provider}: {e}", exc_info=True)
            raise RuntimeError(f"Unexpected error fetching symbols for {market}/{provider}: {e}") from e

    async def fetch_latest_bar(
        self, market: str, provider: str, symbol: str, timeframe: str = "1m", user_id: Optional[str] = None
    ) -> Optional[OHLCVBar]:
        """
        Fetches the single most recent OHLCV bar.

        Args:
            market (str): Market ID.
            provider (str): Provider ID.
            symbol (str): Symbol string.
            timeframe (str): Timeframe string (typically "1m" for true latest).
            user_id (Optional[str]): User ID for context.

        Returns:
            Optional[OHLCVBar]: The latest bar, or None if unavailable.
        """
        if not symbol: raise ValueError("Symbol must be provided for fetch_latest_bar.")
        logger.debug(f"MarketService: Fetching latest '{timeframe}' bar for {market}/{provider}/{symbol}, User: {user_id}")
        try:
            plugin_instance = await self.get_plugin_instance(market, provider, user_id=user_id)
            latest_bar = await plugin_instance.fetch_latest_ohlcv(symbol=symbol, timeframe=timeframe)
            
            if latest_bar:
                logger.info(f"MarketService: Fetched latest '{timeframe}' bar for {symbol} @ {latest_bar['timestamp']}.")
                # Asynchronously save this bar - This could also be a DataOrchestrator responsibility
                # For now, keeping it here if this is a common, direct operation.
                asyncio.create_task(
                    self.save_recent_bars_to_db_and_cache(market, provider, symbol, timeframe, [latest_bar]),
                    name=f"SaveLatestBar_{market}_{provider}_{symbol}"
                )
                return latest_bar
            
            logger.warning(f"MarketService: No latest '{timeframe}' bar returned by plugin for {symbol}.")
            return None
        except PluginError as e:
            logger.error(f"MarketService: PluginError fetching latest bar for {symbol}: {e}", exc_info=True)
            return None # Or re-raise depending on desired behavior
        except Exception as e:
            logger.error(f"MarketService: Unexpected error fetching latest bar for {symbol}: {e}", exc_info=True)
            return None


    async def save_recent_bars_to_db_and_cache(
        self, market: str, provider: str, symbol: str, timeframe: str, bars: List[OHLCVBar],
    ):
        """
        Saves recent bars to the database and attempts to store them in the cache.
        This is a utility method that can be called by various parts of the system (e.g., after fetching latest bar, or by workers).
        """
        if not all([market, provider, symbol, timeframe, bars]):
            logger.warning("MarketService (save_recent_bars): Insufficient data provided. Skipping save.")
            return

        log_key = f"{market}:{provider}:{symbol}@{timeframe}"
        logger.info(f"MarketService: Saving {len(bars)} bars for {log_key} to DB/Cache.")
        
        db_s = MarketService._db_source_instance
        if not db_s: 
            logger.error("MarketService (save_recent_bars): Shared DbSource instance not available!")
            # Optionally, try to create a temporary one if absolutely necessary, though less ideal
            # db_s = DbSource() 
            return

        cache_mgr: Optional[CacheManagerABC] = self._app_config.get("CACHE")
        # OHLCVBar is already a dict-like structure (TypedDict)
        # insert_ohlcv_to_db expects List[Dict[str, Any]]
        # store_1m_bars and set_resampled also expect List[Dict[str, Any]]

        dict_bars = [dict(b) for b in bars] # Ensure they are plain dicts for DB/Cache if TypedDict causes issues with drivers

        try:
            # DbSource().store_ohlcv_bars() would be better if DbSource had such a method.
            # Using the utility function directly for now.
            # Ensuring this is a fire-and-forget task
            asyncio.create_task(
                insert_ohlcv_to_db(market, provider, symbol, timeframe, dict_bars), # Assuming insert_ohlcv_to_db takes List[Dict]
                name=f"SaveRecentDB_{log_key}"
            )
            logger.debug(f"MarketService: DB save task created for {len(bars)} bars of {log_key}.")
        except DatabaseError as dbe:
            logger.error(f"MarketService: DatabaseError scheduling DB save for {log_key}: {dbe}", exc_info=True)
        except Exception as e_db_task:
            logger.error(f"MarketService: Error scheduling DB save task for {log_key}: {e_db_task}", exc_info=True)

        if cache_mgr:
            try:
                if timeframe == "1m": # Only cache raw 1m bars in the "1m group" cache
                    asyncio.create_task(
                        cache_mgr.store_1m_bars(market, provider, symbol, dict_bars), # Assuming this takes List[Dict]
                        name=f"SaveRecent1mCache_{log_key}"
                    )
                    logger.debug(f"MarketService: 1m Cache save task created for {len(bars)} bars of {log_key}.")
                # else:
                    # For non-1m bars fetched (e.g. native non-1m from plugin), if you want to cache them
                    # directly without them being "resampled" by CacheSource's logic, you'd use set_resampled.
                    # cache_key_resampled = f"ohlcv:{market}:{provider}:{symbol}:{timeframe}"
                    # ttl = getattr(cache_mgr, 'ttl_resampled', 300)
                    # asyncio.create_task(
                    #     cache_mgr.set_resampled(cache_key_resampled, dict_bars, ttl),
                    #     name=f"SaveRecentNativeNon1mCache_{log_key}"
                    # )
            except Exception as e_cache_task:
                logger.error(f"MarketService: Error scheduling cache save task for {log_key}: {e_cache_task}", exc_info=True)
    
    async def trigger_historical_backfill_if_needed(
        self, market: str, provider: str, symbol: str, 
        timeframe_context: str, # Timeframe of the original request, for logging/context
        user_id: Optional[str] = None # For getting plugin with user's keys if backfill requires them
    ):
        """
        Triggers a historical backfill for 1m data for the given symbol and provider.
        This instantiates a BackfillManager with a specific plugin instance.
        """
        if not symbol: raise ValueError("Symbol is required for backfill trigger.")
        log_key = f"{market}:{provider}:{symbol}"
        logger.info(f"MarketService: Backfill trigger requested for {log_key} (Context TF: {timeframe_context}), User: {user_id}")

        try:
            # Get a plugin instance, potentially with user keys if backfill needs auth
            # For backfills, often public endpoints are used if possible, or dedicated backfill keys.
            plugin_instance = await self.get_plugin_instance(market, provider, user_id=user_id)
            
            cache_mgr: Optional[CacheManagerABC] = self._app_config.get("CACHE")
            
            backfill_manager = BackfillManager(
                market=market, provider=provider, symbol=symbol,
                plugin=plugin_instance, # Pass the specific plugin instance
                cache=cache_mgr # Pass the cache manager instance
            )
            # The BackfillManager's method is async and likely creates its own task internally
            # if the backfill process is long-running.
            asyncio.create_task(
                backfill_manager.trigger_historical_backfill_if_needed(timeframe_context), # Pass context
                name=f"DispatchBackfillTrigger_{log_key}"
            )
            logger.info(f"MarketService: Backfill trigger task dispatched for {log_key} via BackfillManager.")
        except PluginError as e_plugin:
            logger.error(f"MarketService: PluginError during backfill trigger setup for {log_key}: {e_plugin}", exc_info=True)
            # Depending on policy, might want to notify someone or retry later.
        except Exception as e_setup:
            logger.error(f"MarketService: Unexpected error during backfill trigger setup for {log_key}: {e_setup}", exc_info=True)