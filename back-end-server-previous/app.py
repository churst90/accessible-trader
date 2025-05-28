# app.py

import asyncio
import logging
import time # For health check timestamp
from quart import Quart, jsonify, current_app # current_app for access within lifecycle hooks
from quart_cors import cors

from config import config_class, ConfigError
from app_extensions import configure_logging, init_app_extensions
# Utilities for closing DB and Redis, to be called during shutdown
from app_extensions.db_pool import close_db_pool, get_pool as get_db_pool_util 
from app_extensions.redis_manager import close_redis, get_redis as get_redis_util

from blueprints import init_blueprints
from middleware.error_handler import init_error_handlers # Assuming this is your global error handler setup
from services.market_service import MarketService # Import your refactored MarketService
from services.subscription_service import SubscriptionService # For type hinting

# Module-level logger. Logging should be configured early in create_app.
module_logger = logging.getLogger(__name__) # Use __name__ for this module

def create_app() -> Quart:
    """
    Application Factory Function.

    Creates and configures the Quart application instance. This includes:
    - Loading configuration and validating required settings.
    - Setting up structured logging for the entire application.
    - Initializing the main MarketService.
    - Initializing core application extensions (Database Pool, Redis Cache, PluginLoader,
      SubscriptionService) via app_extensions.init_app_extensions and its before_serving hook.
    - Configuring CORS (Cross-Origin Resource Sharing).
    - Registering API blueprints and global error handlers.
    - Defining a health check endpoint.
    - Managing graceful startup of background tasks and shutdown of application services.
    """
    app = Quart(__name__)

    # 1. Load and Validate Configuration (Fail Fast)
    try:
        config_class.validate() # Validate environment variables and core settings
        app.config.from_object(config_class)
    except ConfigError as e:
        # Use print for critical startup errors before logging might be fully set up
        print(f"CRITICAL CONFIGURATION ERROR: {e}")
        # Also attempt to log if logging has basic setup
        module_logger.critical(f"Configuration validation failed: {e}", exc_info=True)
        raise RuntimeError(f"Fatal Configuration Error: {e}")

    # 2. Configure Logging (as early as possible after config load)
    try:
        configure_logging(app) # Uses app.config["LOG_LEVEL"], LOG_FILE
        # From now on, app.logger can be used for app-level logging if preferred
        app.logger.info("Application configuration loaded and logging configured.")
    except Exception as e_log:
        module_logger.critical(f"Failed to configure logging: {e_log}", exc_info=True)
        raise RuntimeError(f"Logging configuration failed: {e_log}") from e_log

    # 3. Initialize Main Services
    # MarketService is central and needed by SubscriptionService during extension init.
    try:
        app.market_service = MarketService(app.config) # Pass app.config
        app.logger.info("Main MarketService initialized and attached to app context.")
    except Exception as e_ms:
        app.logger.critical(f"CRITICAL - Failed to initialize MarketService: {e_ms}", exc_info=True)
        raise RuntimeError(f"MarketService initialization failed: {e_ms}") from e_ms

    # 4. Initialize Application Extensions (DB, Redis, PluginLoader, SubscriptionService, etc.)
    # init_app_extensions will register a @app.before_serving hook to run further initializations
    # once the event loop is active. This includes starting MarketService's periodic tasks.
    try:
        init_app_extensions(app)
        app.logger.info("Core application extensions and services initialization scheduled via before_serving hook.")
    except Exception as e_ext_init:
        app.logger.critical(f"CRITICAL - Failed to schedule application extensions initialization: {e_ext_init}", exc_info=True)
        raise RuntimeError(f"Application extensions setup failed: {e_ext_init}") from e_ext_init
        
    # 5. Configure CORS
    try:
        trusted_origins_str = app.config.get("TRUSTED_ORIGINS", "")
        if isinstance(trusted_origins_str, str):
            processed_origins = [origin.strip() for origin in trusted_origins_str.split(',') if origin.strip()]
        elif isinstance(trusted_origins_str, list): # Already a list
            processed_origins = [str(o).strip() for o in trusted_origins_str if str(o).strip()]
        else:
            processed_origins = []

        if not processed_origins:
            app.logger.warning(
                "TRUSTED_ORIGINS was empty or invalid. Defaulting to allow all origins ('*'). "
                "Review CORS policy for production environments."
            )
            processed_origins = ["*"] # Default to allow all if not specified or invalid
        
        cors(app, allow_origin=processed_origins)
        app.logger.info(f"CORS configured with trusted origins: {processed_origins}")
    except Exception as e_cors:
        app.logger.error(f"Failed to configure CORS: {e_cors}", exc_info=True)
        # Decide if this is fatal or if default permissive CORS is acceptable for dev

    # 6. Initialize Blueprints and Global Error Handlers
    try:
        init_blueprints(app)
        init_error_handlers(app)
        app.logger.info("API blueprints and global error handlers initialized.")
    except Exception as e_bp_err:
        app.logger.critical(f"CRITICAL - Failed to initialize blueprints or error handlers: {e_bp_err}", exc_info=True)
        raise RuntimeError("Blueprint/ErrorHandler setup failed.") from e_bp_err

    # 7. Define Health Check Endpoint
    @app.route("/health", methods=["GET"])
    async def health_check():
        """Provides a health status of the application and its critical services."""
        db_status = "unavailable"
        redis_status = "unavailable"
        app_status = "degraded" # Assume degraded until checks pass

        # Check Database
        try:
            db_pool = get_db_pool_util(current_app) # Use utility to get pool from current_app.config
            if db_pool:
                async with db_pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                db_status = "ok"
            else:
                current_app.logger.warning("HealthCheck: Database pool (DB_POOL) not found in app config.")
                db_status = "misconfigured" # Pool should be there if init_db_pool succeeded
        except Exception as e_db_health:
            current_app.logger.error(f"HealthCheck: Database connectivity check failed: {e_db_health}", exc_info=False)
            db_status = "error"

        # Check Redis
        try:
            # get_redis_util now returns the CacheManagerABC instance
            cache_service_instance = get_redis_util(current_app)
            if cache_service_instance and hasattr(cache_service_instance, 'redis') and cache_service_instance.redis:
                pong = await cache_service_instance.redis.ping() # Access underlying client's ping
                redis_status = "ok" if pong else "ping_failed"
            elif cache_service_instance: # Instance exists but no 'redis' client
                current_app.logger.warning("HealthCheck: RedisCache instance found, but its 'redis' client attribute is missing or None.")
                redis_status = "misconfigured"
            else: # No CACHE configured
                current_app.logger.info("HealthCheck: RedisCache (CACHE) not configured for this application instance.")
                redis_status = "not_configured" # Not an error if Redis is optional
        except Exception as e_redis_health:
            current_app.logger.error(f"HealthCheck: Redis connectivity check failed: {e_redis_health}", exc_info=False)
            redis_status = "error"

        # Determine overall application status
        if db_status == "ok" and redis_status in ["ok", "not_configured"]:
            app_status = "ok"
        
        response_payload = {
            "application_status": app_status,
            "database_status": db_status,
            "redis_status": redis_status,
            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
            "server_time_epoch_s": time.time()
        }
        http_status_code = 200 if app_status == "ok" else 503 # Service Unavailable
        
        return jsonify(response_payload), http_status_code

    # 8. Application Lifecycle Hooks (Startup tasks are in app_extensions' before_serving)
    # Shutdown logic is centralized here.
    @app.after_serving
    async def shutdown_application_services():
        """Gracefully shuts down application services when the Quart app stops."""
        shutdown_logger = current_app.logger
        shutdown_logger.info("Application Shutdown (after_serving): Starting graceful shutdown of services...")

        # Shutdown SubscriptionService (stops workers)
        subscription_service_instance = current_app.extensions.get('subscription_service')
        if subscription_service_instance and isinstance(subscription_service_instance, SubscriptionService):
            shutdown_logger.info("Shutting down SubscriptionService...")
            try:
                await subscription_service_instance.shutdown()
                shutdown_logger.info("SubscriptionService shut down successfully.")
            except Exception as e_sub_shutdown:
                shutdown_logger.error(f"Error shutting down SubscriptionService: {e_sub_shutdown}", exc_info=True)
        else:
            shutdown_logger.warning("SubscriptionService instance not found in app.extensions for shutdown.")

        # Shutdown MarketService (closes plugin instances, stops periodic tasks)
        if hasattr(current_app, 'market_service') and isinstance(current_app.market_service, MarketService):
            shutdown_logger.info("Shutting down MarketService...")
            try:
                await current_app.market_service.app_shutdown_cleanup()
                shutdown_logger.info("MarketService shut down successfully.")
            except Exception as e_ms_shutdown:
                shutdown_logger.error(f"Error during MarketService shutdown: {e_ms_shutdown}", exc_info=True)
        else:
            shutdown_logger.warning("MarketService instance not found on app context for shutdown.")

        # Close Redis Connection Pool (via utility that uses app.config["CACHE"])
        shutdown_logger.info("Closing Redis connections...")
        try:
            await close_redis(current_app) # This function should handle finding the client in app.config
            shutdown_logger.info("Redis connections closed successfully.")
        except Exception as e_redis_close:
            shutdown_logger.error(f"Error closing Redis connections: {e_redis_close}", exc_info=True)

        # Close Database Connection Pool (via utility that uses app.config["DB_POOL"])
        shutdown_logger.info("Closing database pool...")
        try:
            await close_db_pool(current_app) # This function should handle finding the pool in app.config
            shutdown_logger.info("Database pool closed successfully.")
        except Exception as e_db_close:
            shutdown_logger.error(f"Error closing database pool: {e_db_close}", exc_info=True)

        shutdown_logger.info("Application shutdown sequence complete.")

    app.logger.info("Quart application created and all initial configurations applied. Ready to serve.")
    return app