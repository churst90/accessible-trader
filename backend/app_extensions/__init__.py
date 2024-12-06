import os
import logging
from quart import Quart, current_app
from .db_pool import init_db_pool, close_db_pool, get_pool
from .redis_manager import init_redis, close_redis, get_redis
from config import config_class

def init_app_extensions(app: Quart):
    """
    Initialize all application extensions, including database, Redis, and logging.
    This sets up the before_serving and after_serving hooks so that:
    - The database pool is initialized at startup and closed at shutdown.
    - The Redis connection is initialized at startup and closed at shutdown.
    - Logging is configured at application startup.
    """

    # Logging configuration
    configure_logging(app)

    # Database connection pool lifecycle
    @app.before_serving
    async def before_serving():
        db_pool = await init_db_pool(app)
        app.config["DB_POOL"] = db_pool

        redis_cache = await init_redis(app)
        app.config["CACHE"] = redis_cache

    @app.after_serving
    async def after_serving():
        await close_db_pool(app)
        await close_redis(app)

def configure_logging(app: Quart):
    """
    Configure logging for the application.
    Log level and handlers may be adjusted based on the environment.
    """
    log_level = logging.DEBUG if app.config["ENV"] == "development" else logging.INFO
    log_format = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    handlers = [logging.StreamHandler()]

    log_file = os.getenv("LOG_FILE")
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="a")
        handlers.append(file_handler)

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=handlers
    )
    logging.info(f"Logging configured with level: {logging.getLevelName(log_level)}")
