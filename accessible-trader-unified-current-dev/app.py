# app.py

import asyncio
import logging
import time
from datetime import datetime # Keep this import for your health check
from quart import Quart, jsonify, current_app
from quart_cors import cors
from pathlib import Path

from config import config_class, ConfigError
from app_extensions.auth_db_setup import close_auth_db
from app_extensions.user_configs_db_setup import close_user_configs_db
from app_extensions import configure_logging, init_app_extensions
from app_extensions.db_pool import close_db_pool, get_pool as get_db_pool_util
from app_extensions.redis_manager import close_redis, get_raw_redis_client as get_redis_util

from blueprints import init_blueprints
from views import frontend_bp # Assuming views.py is at the same level as app.py
from middleware.error_handler import init_error_handlers
from services.market_service import MarketService
from services.subscription_service import SubscriptionService
from services.streaming_manager import StreamingManager # Ensure StreamingManager is imported for shutdown
from trading.bot_manager_service import BotManagerService

module_logger = logging.getLogger(__name__) # Use __name__ for module-level logger

def create_app() -> Quart:
    """
    Application Factory Function.

    This function sets up and returns the Quart application instance.
    It involves several key steps:
    1.  Loading and validating the application configuration.
    2.  Configuring logging for the application.
    3.  Initializing main services like MarketService and BotManagerService.
    4.  Scheduling the initialization of application extensions (databases, Redis,
        StreamingManager, SubscriptionService, etc.) to run before the app starts serving.
    5.  Configuring Cross-Origin Resource Sharing (CORS).
    6.  Initializing API blueprints and global error handlers.
    7.  Defining a health check endpoint.
    8.  Registering cleanup functions to run after the app stops serving.
    """
    app = Quart(__name__)

    # --- Configure static folder ---
    # Get the absolute path to the directory where app.py is located
    APP_ROOT = Path(__file__).parent
    # Define the static folder path relative to the app root
    # This assumes your 'static' folder is at the same level as 'app.py'
    app.static_folder = APP_ROOT / "static"
    app.static_url_path = "/static" # How it will be accessed in URLs, e.g. /static/assets/css/base.css

    # --- Configure template folder (Quart usually finds 'templates' by default if it's next to app.py) ---
    # If your 'templates' folder is elsewhere or named differently, you'd set app.template_folder
    # app.template_folder = APP_ROOT / "templates" # This is often the default

    # 1. Load and Validate Configuration (Fail Fast)
    try:
        config_class.validate()
        app.config.from_object(config_class)
        # Ensure module_logger uses configured level after this point if setup changes root logger
    except ConfigError as e:
        # Use print for critical startup errors before logging might be fully configured
        print(f"CRITICAL CONFIGURATION ERROR: {e}")
        # Also attempt to log if logging might be partially working or to a default handler
        logging.getLogger(__name__).critical(f"Configuration validation failed: {e}", exc_info=True)
        raise RuntimeError(f"Fatal Configuration Error: {e}")

    # 2. Configure Logging (as early as possible after config load)
    try:
        configure_logging(app) # This sets up app.logger and other loggers
        module_logger.info("Application configuration loaded and logging configured.") # Use the module logger
    except Exception as e_log:
        # If logging setup itself fails, print and attempt basic logging
        print(f"CRITICAL LOGGING CONFIGURATION ERROR: {e_log}")
        logging.getLogger(__name__).critical(f"Failed to configure logging: {e_log}", exc_info=True)
        raise RuntimeError(f"Logging configuration failed: {e_log}") from e_log

    # 3. Initialize Main Services directly attached to app (if needed before extensions)
    try:
        app.market_service = MarketService(app.config)
        app.logger.info("Main MarketService initialized and attached to app context.")
    except Exception as e_ms:
        app.logger.critical(f"CRITICAL - Failed to initialize MarketService: {e_ms}", exc_info=True)
        raise RuntimeError(f"MarketService initialization failed: {e_ms}") from e_ms

    try:
        if not hasattr(app, 'market_service') or not app.market_service:
            app.logger.critical("Cannot initialize BotManagerService: MarketService is not available.")
            raise RuntimeError("BotManagerService cannot be initialized without MarketService.")
        
        app.bot_manager_service = BotManagerService(app.config, app.market_service)
        app.logger.info("BotManagerService initialized and attached to app context.")
    except Exception as e_bms:
        app.logger.critical(f"CRITICAL - Failed to initialize BotManagerService: {e_bms}", exc_info=True)
        raise RuntimeError(f"BotManagerService initialization failed: {e_bms}") from e_bms

    # 4. Schedule Initialization of Application Extensions and other Services
    # These will be initialized in the `before_serving` hook defined in `init_app_extensions`.
    # This includes DB connections, Redis, StreamingManager, SubscriptionService, etc.
    try:
        init_app_extensions(app) # This function registers the @app.before_serving tasks
        app.logger.info("Core application extensions and services initialization scheduled via before_serving hook.")
    except Exception as e_ext_init:
        app.logger.critical(f"CRITICAL - Failed to schedule application extensions initialization: {e_ext_init}", exc_info=True)
        raise RuntimeError(f"Application extensions setup failed: {e_ext_init}") from e_ext_init
        
    # 5. Configure CORS
    try:
        trusted_origins_str = app.config.get("TRUSTED_ORIGINS", "")
        if isinstance(trusted_origins_str, str):
            processed_origins = [origin.strip() for origin in trusted_origins_str.split(',') if origin.strip()]
        elif isinstance(trusted_origins_str, list): # Already a list in config
            processed_origins = [str(o).strip() for o in trusted_origins_str if str(o).strip()]
        else:
            processed_origins = []
        
        if not processed_origins:
            app.logger.warning("TRUSTED_ORIGINS was empty or invalid. Defaulting to allow all origins ('*'). Review CORS policy for production environments.")
            processed_origins = ["*"] # Default to all if not specified or invalid
            
        cors(app, allow_origin=processed_origins) # allow_credentials=True, allow_methods=["*"], allow_headers=["*"] can be added
        app.logger.info(f"CORS configured with trusted origins: {processed_origins}")
    except Exception as e_cors:
        app.logger.error(f"Failed to configure CORS: {e_cors}", exc_info=True)
        # Depending on policy, might raise an error or continue with default/no CORS.

    # 6. Initialize Blueprints and Global Error Handlers
    try:
        init_blueprints(app)
        app.register_blueprint(frontend_bp)
        init_error_handlers(app)
        app.logger.info("API blueprints, front end view blueprint and global error handlers initialized.")
    except Exception as e_bp_err:
        app.logger.critical(f"CRITICAL - Failed to initialize blueprints or error handlers: {e_bp_err}", exc_info=True)
        raise RuntimeError("Blueprint/ErrorHandler setup failed.") from e_bp_err

    # 7. Define Health Check Endpoint
    @app.route("/health", methods=["GET"])
    async def health_check():
        """
        Provides a health check endpoint for monitoring the application's status,
        including connectivity to the database and Redis.
        """
        db_status = "unavailable"
        redis_status = "unavailable"
        app_status = "degraded" # Assume degraded until checks pass

        # Check Database Pool (PostgreSQL - OHLCV)
        try:
            db_pool = get_db_pool_util(current_app) # Utility from app_extensions.db_pool
            if db_pool:
                async with db_pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                db_status = "ok"
            else:
                current_app.logger.warning("HealthCheck: Database pool (DB_POOL) not found in app context.")
                db_status = "misconfigured" # Pool not initialized
        except Exception as e_db_health:
            current_app.logger.error(f"HealthCheck: Database connectivity check failed: {e_db_health}", exc_info=False) # exc_info=False to reduce noise
            db_status = "error"

        # Check Redis Connection (Raw Client)
        try:
            # MODIFIED: Use get_redis_util which now points to get_raw_redis_client
            raw_redis_client = get_redis_util(current_app) 
            if raw_redis_client:
                pong = await raw_redis_client.ping()
                redis_status = "ok" if pong else "ping_failed"
            else:
                # This case implies Redis was not configured/enabled or init failed.
                # init_redis in redis_manager raises RuntimeError if REDIS_URL is missing or connection fails,
                # so if we reach here and raw_redis_client is None, it might be that CACHE_ENABLED=False
                # or some other logic path in init_redis was taken.
                # For health check, if raw_redis_client isn't there, it means Redis isn't available as expected by this check.
                # Check if Redis is supposed to be configured (e.g., based on REDIS_URL presence)
                if current_app.config.get("REDIS_URL"):
                    current_app.logger.warning("HealthCheck: Raw Redis client not found via get_redis_util, but REDIS_URL is configured.")
                    redis_status = "misconfigured" # Expected but not found
                else:
                    current_app.logger.info("HealthCheck: Redis (raw client) not configured for this application instance (no REDIS_URL).")
                    redis_status = "not_configured" # Intentionally not set up
        except Exception as e_redis_health:
            current_app.logger.error(f"HealthCheck: Redis connectivity check failed: {e_redis_health}", exc_info=False)
            redis_status = "error"
            
        # Determine overall application status
        if db_status == "ok" and redis_status in ["ok", "not_configured"]:
            # App is OK if DB is fine and Redis is either OK or intentionally not configured.
            # If Redis is "misconfigured" or "error", app status remains "degraded".
            app_status = "ok"

        response_payload = {
            "application_status": app_status,
            "database_status": db_status,
            "redis_status": redis_status,
            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
            "server_time_epoch_s": time.time()
        }
        http_status_code = 200 if app_status == "ok" else 503 # Service Unavailable if degraded
        return jsonify(response_payload), http_status_code


    @app.after_serving
    async def shutdown_application_services():
        """
        Gracefully shuts down all application services and connections after the
        application has finished serving requests.
        The order of shutdown is important to prevent errors during termination.
        """
        shutdown_logger = current_app.logger # Use the configured app logger
        shutdown_logger.info("Application Shutdown (after_serving): Starting graceful shutdown of services...")

        # Shutdown BotManagerService (depends on MarketService)
        if hasattr(current_app, 'bot_manager_service') and current_app.bot_manager_service:
            shutdown_logger.info("Shutting down BotManagerService and all active bots...")
            try:
                await current_app.bot_manager_service.shutdown_all_bots()
                shutdown_logger.info("BotManagerService and all bots processed for shutdown.")
            except Exception as e_bms_shutdown:
                shutdown_logger.error(f"Error shutting down BotManagerService: {e_bms_shutdown}", exc_info=True)
        else:
            shutdown_logger.warning("BotManagerService instance not found for shutdown.")

        # Shutdown SubscriptionService (depends on StreamingManager, MarketService, Redis)
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

        # ADDED: Shutdown StreamingManager (depends on MarketService, Redis)
        # This should be after SubscriptionService has released its streams from the manager.
        streaming_manager_instance = current_app.extensions.get('streaming_manager')
        if streaming_manager_instance and isinstance(streaming_manager_instance, StreamingManager):
            shutdown_logger.info("Shutting down StreamingManager...")
            try:
                await streaming_manager_instance.shutdown()
                shutdown_logger.info("StreamingManager shut down successfully.")
            except Exception as e_sm_shutdown:
                shutdown_logger.error(f"Error shutting down StreamingManager: {e_sm_shutdown}", exc_info=True)
        else:
            shutdown_logger.warning("StreamingManager instance not found in app.extensions for shutdown.")
        
        # Shutdown MarketService (depends on DBs, Redis for its cache source if used by DataOrchestrator)
        if hasattr(current_app, 'market_service') and isinstance(current_app.market_service, MarketService):
            shutdown_logger.info("Shutting down MarketService...")
            try:
                await current_app.market_service.app_shutdown_cleanup()
                shutdown_logger.info("MarketService shut down successfully.")
            except Exception as e_ms_shutdown:
                shutdown_logger.error(f"Error during MarketService shutdown: {e_ms_shutdown}", exc_info=True)
        else:
            shutdown_logger.warning("MarketService instance not found on app context for shutdown.")

        # Close Redis Connection Pool (used by StreamingManager, SubscriptionService, CacheManager)
        shutdown_logger.info("Closing Redis connections...")
        try:
            await close_redis(current_app) # From app_extensions.redis_manager
            shutdown_logger.info("Redis connections closed successfully.")
        except Exception as e_redis_close:
            shutdown_logger.error(f"Error closing Redis connections: {e_redis_close}", exc_info=True)

        # Close Database Connection Pool (PostgreSQL - OHLCV)
        shutdown_logger.info("Closing OHLCV database pool (PostgreSQL)...")
        try:
            await close_db_pool(current_app) # From app_extensions.db_pool
            shutdown_logger.info("OHLCV database pool (PostgreSQL) closed successfully.")
        except Exception as e_db_close:
            shutdown_logger.error(f"Error closing OHLCV database pool (PostgreSQL): {e_db_close}", exc_info=True)

        # Close Auth Database (userdb - MariaDB)
        shutdown_logger.info("Closing Auth database (userdb) engine...")
        try:
            await close_auth_db(current_app) # From app_extensions.auth_db_setup
            shutdown_logger.info("Auth database (userdb) engine closed successfully.")
        except Exception as e_auth_db_close:
            shutdown_logger.error(f"Error closing Auth database (userdb) engine: {e_auth_db_close}", exc_info=True)

        # Close User Configs Database (user_configs_db - MariaDB)
        shutdown_logger.info("Closing User Configs database (user_configs_db) engine...")
        try:
            await close_user_configs_db(current_app) # From app_extensions.user_configs_db_setup
            shutdown_logger.info("User Configs database (user_configs_db) engine closed successfully.")
        except Exception as e_user_configs_db_close:
            shutdown_logger.error(f"Error closing User Configs database (user_configs_db) engine: {e_user_configs_db_close}", exc_info=True)

        shutdown_logger.info("Application shutdown sequence complete.")

    app.logger.info("Quart application created and all initial configurations applied. Ready to serve.")
    return app