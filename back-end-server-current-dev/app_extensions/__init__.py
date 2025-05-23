# app_extensions/__init__.py

import asyncio
import os
import logging
import logging.config # For dictConfig
from quart import Quart, current_app # current_app can be useful within callbacks

# Import plugin loader (class methods will be used)
from plugins import PluginLoader

# Import utility functions for initializing/closing extensions
from .db_pool import init_db_pool, close_db_pool # These utilities can still be used by app.py for shutdown
from .redis_manager import init_redis, close_redis # Same for Redis utilities

# Import Service Classes for type hinting and instantiation checks
from services.subscription_service import SubscriptionService
from services.market_service import MarketService as MarketServiceType # For type hinting

# Module-level logger
module_logger = logging.getLogger(__name__)

def configure_logging(app: Quart):
    """
    Configures logging for the entire application based on app.config settings.
    Uses logging.dictConfig for a structured setup.
    """
    log_level_name = app.config.get("LOG_LEVEL", "INFO").upper()
    # Ensure the log level is a valid one, default to INFO if not
    log_level = getattr(logging, log_level_name, logging.INFO)
    log_file = app.config.get("LOG_FILE")

    # Base handler configuration
    handlers_config = {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'stream': 'ext://sys.stdout', # Output to stdout
        }
    }
    # Base list of handlers to apply to loggers
    active_handlers = ['console']

    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except OSError as e:
                # Log to console since file logging might not be set up yet
                print(f"ERROR: Could not create log directory {log_dir}: {e}")
        
        handlers_config['file'] = {
            'class': 'logging.handlers.TimedRotatingFileHandler', # Example for production
            'formatter': 'default',
            'filename': log_file,
            'when': 'midnight', # Rotate daily
            'backupCount': 7,   # Keep 7 old log files
            'encoding': 'utf-8'
        }
        active_handlers.append('file')

    # Define the logging configuration dictionary
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
            # Application specific loggers
            'app': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'MarketService': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'SubscriptionService': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'SubscriptionWorker': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
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
            # Blueprints
            'market_blueprint': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'auth_blueprint': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'user_blueprint': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'WebSocketBlueprint': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            # Quart and Hypercorn loggers
            'quart.app': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'quart.serving': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
            'hypercorn.access': {'level': 'WARNING', 'handlers': active_handlers, 'propagate': False},
            'hypercorn.error': {'level': log_level, 'handlers': active_handlers, 'propagate': False},
        },
        'root': { # Catch-all root logger
            'handlers': active_handlers,
            'level': log_level,
        },
    }

    try:
        logging.config.dictConfig(log_config_dict)
        # Use the app's configured logger after setup
        app.logger.info(
            f"Logging configured. Effective root log level: {logging.getLevelName(logging.getLogger().getEffectiveLevel())}"
        )
        if log_file:
            app.logger.info(f"Logging to file: {log_file}")
    except Exception as e:
        # Fallback to basicConfig if dictConfig fails, ensuring some logging output
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
        logging.getLogger(__name__).error("dictConfig for logging failed. Fell back to basicConfig.", exc_info=True)
        # Raise the error after attempting fallback logging so it's visible
        raise RuntimeError(f"Failed to configure logging with dictConfig: {e}") from e


def init_app_extensions(app: Quart):
    """
    Initializes application extensions and registers application lifecycle hooks.
    This function sets up a `before_serving` callback to initialize services
    once the application configuration is loaded and the event loop is running.

    Args:
        app (Quart): The Quart application instance.
    """
    if not hasattr(app, 'extensions'):
        app.extensions = {} # General purpose dict for extensions if needed

    @app.before_serving
    async def startup_extensions_and_services():
        """
        Tasks to run after app config is loaded and Quart's event loop is running,
        but before the app starts serving requests.
        Initializes DB, Redis, PluginLoader, MarketService, SubscriptionService,
        and starts background tasks.
        """
        # Use current_app.logger here as it's configured by now.
        startup_logger = current_app.logger 
        startup_logger.info("Application Extensions (before_serving): Starting initialization sequence...")

        # 1. Discover Plugins (using PluginLoader class methods)
        startup_logger.info("App Extensions: Discovering plugins...")
        try:
            PluginLoader.discover_plugins(base_module_path="plugins") # Assuming plugins are in "plugins" package
            startup_logger.info(f"App Extensions: Plugins discovered. Available keys: {PluginLoader.list_plugins()}")
        except Exception as e_plugins:
            startup_logger.critical(f"App Extensions: CRITICAL - Failed to discover plugins: {e_plugins}", exc_info=True)
            raise RuntimeError("Plugin discovery failed, application cannot start.") from e_plugins

        # 2. Initialize Database Pool
        startup_logger.info("App Extensions: Initializing database pool...")
        try:
            db_pool = await init_db_pool(app) # init_db_pool uses app.config
            app.config["DB_POOL"] = db_pool # Store for app-wide access by key "DB_POOL"
            startup_logger.info("App Extensions: Database pool initialized and stored in app.config['DB_POOL'].")
        except Exception as e_db:
            startup_logger.critical(f"App Extensions: CRITICAL - Failed to initialize database pool: {e_db}", exc_info=True)
            raise RuntimeError("Database initialization failed.") from e_db

        # 3. Initialize Redis Cache
        startup_logger.info("App Extensions: Initializing Redis cache manager...")
        try:
            # init_redis initializes RedisCache and stores it in app.config["CACHE"]
            await init_redis(app) 
            if not app.config.get("CACHE"): # Should be set by init_redis
                 startup_logger.error("App Extensions: init_redis completed but app.config['CACHE'] was not set!")
                 # This might be a critical failure depending on app requirements.
            startup_logger.info("App Extensions: Redis cache manager initialized (instance expected in app.config['CACHE']).")
        except Exception as e_redis:
            startup_logger.critical(f"App Extensions: CRITICAL - Failed to initialize Redis cache: {e_redis}", exc_info=True)
            raise RuntimeError("Redis initialization failed.") from e_redis
        
        # 4. MarketService Initialization (should have happened in app.py's create_app)
        # We just confirm it's there.
        if not hasattr(app, 'market_service') or not isinstance(app.market_service, MarketServiceType):
            startup_logger.critical("App Extensions: CRITICAL - MarketService instance (app.market_service) not found or is of incorrect type. It must be initialized in create_app().")
            raise RuntimeError("MarketService not properly initialized in the application factory.")
        startup_logger.info("App Extensions: MarketService instance confirmed on app context.")

        # 5. Initialize SubscriptionService (depends on MarketService)
        startup_logger.info("App Extensions: Initializing SubscriptionService...")
        try:
            # SubscriptionService __init__ expects the market_service instance.
            sub_service_instance = SubscriptionService(market_service_instance=app.market_service)
            app.extensions['subscription_service'] = sub_service_instance # Store for access by WebSocket blueprint
            startup_logger.info("App Extensions: SubscriptionService initialized and stored in app.extensions['subscription_service'].")
        except Exception as e_sub_svc:
            startup_logger.critical(f"App Extensions: CRITICAL - Failed to initialize SubscriptionService: {e_sub_svc}", exc_info=True)
            raise RuntimeError("SubscriptionService initialization failed.") from e_sub_svc

        # 6. Start MarketService's background tasks (e.g., idle plugin cleanup)
        startup_logger.info("App Extensions: Starting MarketService background tasks...")
        try:
            await app.market_service.start_periodic_cleanup()
            startup_logger.info("App Extensions: MarketService periodic plugin cleanup task started.")
        except Exception as e_ms_task:
            startup_logger.error(f"App Extensions: Failed to start MarketService background tasks: {e_ms_task}", exc_info=True)
            # Depending on criticality, you might want to raise an error.

        startup_logger.info("Application Extensions (before_serving): Initialization sequence completed successfully.")

    # Note: Shutdown logic for DB_POOL, CACHE, MarketService, and SubscriptionService
    # should be handled in app.py's @app.after_serving decorated function
    # to ensure proper order and centralized management of shutdown.
    # This init_app_extensions focuses only on startup registrations.

    module_logger.info("init_app_extensions: Application startup hooks registered. Shutdown is orchestrated by app.py.")