# app_extensions/__init__.py

import asyncio
import os
import logging
import logging.config # For dictConfig
from quart import Quart, current_app 
from typing import Optional # For type hinting raw_redis_client

# Redis client for Pub/Sub and other services
from redis.asyncio import Redis as AsyncRedis 
from .redis_manager import init_redis, close_redis, get_raw_redis_client

# Plugin loader
from plugins import PluginLoader

# Database initializers
from .db_pool import init_db_pool, close_db_pool 
from .auth_db_setup import init_auth_db, close_auth_db
from .user_configs_db_setup import init_user_configs_db, close_user_configs_db

# Service Classes
from services.market_service import MarketService 
from services.subscription_service import SubscriptionService
from services.streaming_manager import StreamingManager # Import the new StreamingManager
# from trading.bot_manager_service import BotManagerService # Already imported in app.py, ensure it's available on current_app

module_logger = logging.getLogger(__name__)

def configure_logging(app: Quart):
    # ... (your existing comprehensive configure_logging function - keep as is) ...
    # (ensure it's the same as the one you posted that works)
    log_level_name = app.config.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    log_file = app.config.get("LOG_FILE")
    handlers_config = {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'stream': 'ext://sys.stdout', 
        }
    }
    active_handlers = ['console']
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except OSError as e:
                print(f"ERROR: Could not create log directory {log_dir}: {e}")
        handlers_config['file'] = {
            'class': 'logging.handlers.TimedRotatingFileHandler', 
            'formatter': 'default',
            'filename': log_file,
            'when': 'midnight', 
            'backupCount': 7,  
            'encoding': 'utf-8'
        }
        active_handlers.append('file')
    log_config_dict = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'format': '%(asctime)s - %(levelname)-8s - [%(name)-20s] - %(module)s.%(funcName)s:%(lineno)d - %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            },
        },
        'handlers': handlers_config,
        'loggers': { 
            'app': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'MarketService': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'SubscriptionService': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'StreamingManager': {'level': log_level, 'handlers': active_handlers, 'propagate': False}, # Added
            'SubscriptionWorker': {'level': log_level, 'handlers': active_handlers, 'propagate': False}, # Will be deprecated
            'DataOrchestrator': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'BackfillManager': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'PluginLoader': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'CryptoPlugin': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'AlpacaPlugin': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'DbSource': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'CacheSource': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'AggregateSource': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'PluginSource': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'CacheManager': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'DBPool': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'RedisManager': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'DatabaseUtils': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'Response': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'market_blueprint': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'auth_blueprint': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'user_blueprint': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'WebSocketBlueprint': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'quart.app': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'quart.serving': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'hypercorn.access': {'level': 'WARNING', 'handlers': active_handlers, 'propagate': False},
            'hypercorn.error': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
        },
        'root': { 
            'handlers': active_handlers,
            'level': log_level,
        },
    }
    try:
        logging.config.dictConfig(log_config_dict)
        app.logger.info(
            f"Logging configured. Effective root log level: {logging.getLevelName(logging.getLogger().getEffectiveLevel())}"
        )
        if log_file:
            app.logger.info(f"Logging to file: {log_file}")
    except Exception as e:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
        logging.getLogger(__name__).error("dictConfig for logging failed. Fell back to basicConfig.", exc_info=True)
        raise RuntimeError(f"Failed to configure logging with dictConfig: {e}") from e


def init_app_extensions(app: Quart):
    """
    Initializes application extensions and registers application lifecycle hooks.
    """
    if not hasattr(app, 'extensions'):
        app.extensions = {}

    @app.before_serving
    async def startup_extensions_and_services():
        startup_logger = current_app.logger 
        startup_logger.info("App Extensions (before_serving): Starting initialization sequence...")

        # 1. Discover Plugins
        # ... (keep your existing plugin discovery) ...
        try:
            PluginLoader.discover_plugins(base_module_path="plugins")
            startup_logger.info(f"App Extensions: Plugins discovered. Keys: {PluginLoader.list_plugins()}")
        except Exception as e: startup_logger.critical(f"CRITICAL: Plugin discovery failed: {e}", exc_info=True); raise

        # 2. Initialize OHLCV DB Pool (PostgreSQL)
        # ... (keep your existing init_db_pool) ...
        try:
            db_pool = await init_db_pool(app)
            app.config["DB_POOL"] = db_pool
            startup_logger.info("App Extensions: OHLCV DB Pool (PostgreSQL) initialized.")
        except Exception as e: startup_logger.critical(f"CRITICAL: OHLCV DB Pool init failed: {e}", exc_info=True); raise

        # 3. Initialize Redis (Client and Cache Service)
        #    init_redis now stores raw client in app.extensions["redis_client_raw"]
        #    and RedisCache instance in app.config["CACHE"]
        # ... (keep your existing init_redis call) ...
        try:
            await init_redis(app)
            startup_logger.info("App Extensions: Redis client and CacheManager initialized.")
        except Exception as e: startup_logger.critical(f"CRITICAL: Redis init failed: {e}", exc_info=True); raise
        
        # Ensure raw_redis_client is available for services that need it
        raw_redis_client = get_raw_redis_client(current_app)
        if not raw_redis_client:
            startup_logger.critical("App Extensions: CRITICAL - Raw Redis client not found after init_redis.")
            raise RuntimeError("Raw Redis client initialization failed or not stored correctly.")

        # 4. Confirm MarketService (already initialized in app.py's create_app)
        market_service_instance = getattr(current_app, 'market_service', None)
        if not isinstance(market_service_instance, MarketService): # Check type too
            startup_logger.critical("App Extensions: CRITICAL - MarketService not found on app or incorrect type.")
            raise RuntimeError("MarketService not properly initialized in create_app.")
        startup_logger.info("App Extensions: MarketService instance confirmed.")

        # --- NEW: Initialize StreamingManager ---
        # StreamingManager depends on MarketService and the raw Redis client.
        startup_logger.info("App Extensions: Initializing StreamingManager...")
        try:
            streaming_manager_instance = StreamingManager(
                market_service=market_service_instance, 
                redis_client=raw_redis_client,
                app_config=current_app.config
            )
            current_app.extensions['streaming_manager'] = streaming_manager_instance
            startup_logger.info("App Extensions: StreamingManager initialized.")
        except Exception as e_sm:
            startup_logger.critical(f"App Extensions: CRITICAL - Failed to initialize StreamingManager: {e_sm}", exc_info=True)
            raise RuntimeError("StreamingManager initialization failed.") from e_sm
        
        # 5. Initialize SubscriptionService (now depends on MarketService, StreamingManager, and raw Redis client)
        startup_logger.info("App Extensions: Initializing SubscriptionService...")
        try:
            subscription_service_instance = SubscriptionService(
                market_service_instance=market_service_instance,
                streaming_manager_instance=streaming_manager_instance, # Pass StreamingManager
                redis_client=raw_redis_client                        # Pass raw Redis client
            )
            current_app.extensions['subscription_service'] = subscription_service_instance
            startup_logger.info("App Extensions: SubscriptionService initialized.")
        except Exception as e_sub_svc:
            startup_logger.critical(f"App Extensions: CRITICAL - Failed to initialize SubscriptionService: {e_sub_svc}", exc_info=True)
            raise RuntimeError("SubscriptionService initialization failed.") from e_sub_svc

        # 6. Start MarketService's background tasks
        # ... (keep existing call) ...
        try:
            await market_service_instance.start_periodic_cleanup()
            startup_logger.info("App Extensions: MarketService periodic tasks started.")
        except Exception as e: startup_logger.error(f"App Extensions: Error starting MarketService tasks: {e}", exc_info=True)

        # 7. Initialize Auth Database (userdb)
        # ... (keep existing call) ...
        try:
            await init_auth_db(current_app)
            startup_logger.info("App Extensions: Auth DB (userdb) initialized.")
        except Exception as e: startup_logger.critical(f"CRITICAL: Auth DB init failed: {e}", exc_info=True); raise

        # 8. Initialize User Configs Database
        # ... (keep existing call) ...
        try:
            await init_user_configs_db(current_app)
            startup_logger.info("App Extensions: User Configs DB initialized.")
        except Exception as e: startup_logger.critical(f"CRITICAL: User Configs DB init failed: {e}", exc_info=True); raise
            
        # 9. Start up active trading bots (BotManagerService should be on current_app from app.py)
        bot_manager = getattr(current_app, 'bot_manager_service', None)
        if bot_manager:
            startup_logger.info("App Extensions: Starting active trading bots...")
            try:
                await bot_manager.startup_bots()
                startup_logger.info("App Extensions: Active bots startup sequence initiated.")
            except Exception as e_bots: startup_logger.error(f"App Extensions: Error during bot startup: {e_bots}", exc_info=True)
        else:
            startup_logger.warning("App Extensions: BotManagerService not found. Skipping bot startup.")
            
        startup_logger.info("Application Extensions (before_serving): Full initialization sequence completed.")

    module_logger.info("init_app_extensions: Application startup hooks registered.")