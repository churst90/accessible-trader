# app_extensions/__init__.py

import asyncio
import os # Keep for potential future use (e.g., loading config from env vars more directly)
import logging
import logging.config # For potential future dictConfig use
from quart import Quart, current_app 

# Import plugin loader
from plugins import PluginLoader

# Import extension initializers/closers
from .db_pool import init_db_pool, close_db_pool
from .redis_manager import init_redis, close_redis

# Import the CLASS, not the instance, for SubscriptionService
from services.subscription_service import SubscriptionService

def configure_logging(app: Quart):
    """Configures logging based on the application config."""
    log_level_name = app.config.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    log_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'format': '%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'default',
                'stream': 'ext://sys.stdout',
            },
        },
        'loggers': {
            '': { # Root logger
                'handlers': ['console'],
                'level': log_level,
                'propagate': False, # Avoid duplicate logs if other loggers also handle
            },
            'asyncio': {'level': 'WARNING', 'propagate': False},
            'asyncpg': {'level': 'WARNING', 'propagate': False},
            'aiohttp': {'level': 'WARNING', 'propagate': False},
            'websockets': {'level': 'INFO', 'propagate': False}, # Quart's WebSocket library
            'quart.app': {'level': log_level, 'propagate': False, 'handlers': ['console']}, # Ensure quart app logs are also controlled
            'quart.serving': {'level': log_level, 'propagate': False, 'handlers': ['console']},
            'hypercorn.access': {'level': 'WARNING', 'propagate': False, 'handlers': ['console']},
            'hypercorn.error': {'level': 'INFO', 'propagate': False, 'handlers': ['console']},
            # Add your application's specific loggers here if needed
            'MarketService': {'level': log_level, 'propagate': False, 'handlers': ['console']},
            'SubscriptionService': {'level': log_level, 'propagate': False, 'handlers': ['console']},
            'WebSocketBlueprint': {'level': log_level, 'propagate': False, 'handlers': ['console']},
            'PluginLoader': {'level': log_level, 'propagate': False, 'handlers': ['console']},
            'CryptoPlugin': {'level': log_level, 'propagate': False, 'handlers': ['console']},
            'AlpacaPlugin': {'level': log_level, 'propagate': False, 'handlers': ['console']},
            'DBPool': {'level': log_level, 'propagate': False, 'handlers': ['console']},
            'RedisManager': {'level': log_level, 'propagate': False, 'handlers': ['console']},
            'DatabaseUtils': {'level': log_level, 'propagate': False, 'handlers': ['console']},
            'Cache': {'level': log_level, 'propagate': False, 'handlers': ['console']},
            'Response': {'level': log_level, 'propagate': False, 'handlers': ['console']},
            'market_blueprint': {'level': log_level, 'propagate': False, 'handlers': ['console']},
        },
    }

    log_file = app.config.get("LOG_FILE")
    if log_file:
        # Ensure the directory for the log file exists
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            
        log_config['handlers']['file'] = {
            'class': 'logging.FileHandler',
            'formatter': 'default',
            'filename': log_file,
            'mode': 'a',
        }
        # Add file handler to all relevant loggers
        for logger_name in log_config['loggers']:
            if 'handlers' in log_config['loggers'][logger_name]:
                 log_config['loggers'][logger_name]['handlers'].append('file')
            else: # For root logger if handlers list wasn't predefined
                 log_config['loggers'][logger_name]['handlers'] = ['console', 'file']


    logging.config.dictConfig(log_config)
    
    # Use Quart's logger for this initial message to ensure it's set up
    app_logger = logging.getLogger('quart.app') # Or just logging.getLogger() if root is desired
    app_logger.info(f"Logging configured. Effective Level: {logging.getLevelName(app_logger.getEffectiveLevel())}")
    if log_file:
        app_logger.info(f"Logging to file: {log_file}")


def init_app_extensions(app: Quart):
    """Initializes application extensions and registers lifecycle hooks."""
    if not hasattr(app, 'extensions'):
        app.extensions = {}

    @app.before_serving
    async def startup():
        app_logger = current_app.logger # Use Quart's app logger

        app_logger.info("Discovering plugins...")
        try:
            PluginLoader.discover_plugins(base_module_path="plugins")
            app_logger.info(f"Plugins discovered. Available keys: {PluginLoader.list_plugins()}")
        except Exception as e:
            app_logger.critical(f"Failed to discover plugins: {e}", exc_info=True)
            raise RuntimeError("Plugin discovery failed, cannot start application.") from e

        app_logger.info("Initializing database pool...")
        try:
            db_pool = await init_db_pool(app)
            app.config["DB_POOL"] = db_pool
            app_logger.info("Database pool initialized.")
        except Exception as e:
            app_logger.critical(f"Failed to initialize database pool: {e}", exc_info=True)
            raise RuntimeError("Database initialization failed.") from e

        app_logger.info("Initializing Redis cache...")
        try:
            await init_redis(app) # Stores cache instance in app.config['CACHE']
            app_logger.info("Redis cache initialized.")
        except Exception as e:
            app_logger.critical(f"Failed to initialize Redis cache: {e}", exc_info=True)
            raise RuntimeError("Redis initialization failed.") from e

        app_logger.info("Initializing SubscriptionService...")
        try:
            sub_service_instance = SubscriptionService()
            app.extensions['subscription_service'] = sub_service_instance
            app_logger.info("SubscriptionService initialized.")
        except Exception as e:
            app_logger.critical(f"Failed to initialize SubscriptionService: {e}", exc_info=True)
            raise RuntimeError("SubscriptionService initialization failed.") from e

        app_logger.info("Application startup sequence completed successfully.")

    @app.after_serving
    async def shutdown():
        app_logger = current_app.logger # Use Quart's app logger for shutdown messages
        app_logger.info("Beginning graceful shutdown...")

        sub_service_instance = app.extensions.get('subscription_service')
        if sub_service_instance:
            try:
                app_logger.info("Attempting to shut down SubscriptionService...")
                await sub_service_instance.shutdown()
                app_logger.info("Subscriptionservice shut down successfully.")
            except Exception as e:
                app_logger.error(f"Error shutting down SubscriptionService: {e}", exc_info=True)
        else:
            app_logger.warning("SubscriptionService instance not found during shutdown.")

        loaded_plugin_keys = list(PluginLoader._instances.keys())
        if loaded_plugin_keys:
            app_logger.info(f"Closing loaded plugin instances: {loaded_plugin_keys}")
            close_tasks = []
            for key in loaded_plugin_keys:
                try:
                    plugin_instance = PluginLoader._instances.get(key)
                    if plugin_instance and hasattr(plugin_instance, 'close'):
                        close_tasks.append(asyncio.create_task(plugin_instance.close(), name=f"PluginClose_{key}"))
                except Exception as e:
                    app_logger.error(f"Error preparing to close plugin '{key}': {e}", exc_info=True)
            
            if close_tasks:
                results = await asyncio.gather(*close_tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    # Ensure task_name is retrieved from the task object itself
                    task_name = close_tasks[i].get_name() if hasattr(close_tasks[i], 'get_name') else f"PluginTask_{i}"
                    if isinstance(result, Exception):
                        app_logger.error(f"Error during closure of {task_name}: {result}", exc_info=True) # Pass exception directly to exc_info
                    else:
                        app_logger.info(f"{task_name} closed successfully.")
        else:
            app_logger.info("No plugin instances to close.")

        app_logger.info("Attempting to close Redis connection pool...")
        try:
            await close_redis(app)
            app_logger.info("Redis connection pool closed.")
        except Exception as e:
            app_logger.error(f"Error closing Redis connection: {e}", exc_info=True)

        app_logger.info("Attempting to close database connection pool...")
        try:
            await close_db_pool(app)
            app_logger.info("Database connection pool closed.")
        except Exception as e:
            app_logger.error(f"Error closing database pool: {e}", exc_info=True)

        app_logger.info("Graceful shutdown complete.")