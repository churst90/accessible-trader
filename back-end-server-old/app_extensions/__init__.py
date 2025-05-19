# app_extensions/__init__.py

import os
import logging
from quart import Quart

from .db_pool import init_db_pool, close_db_pool
from .redis_manager import init_redis, close_redis
from services.subscription_manager import subscription_manager
from services.ws_registry import close_all as close_all_ws

def configure_logging(app: Quart):
    level    = logging.DEBUG if app.config["ENV"] == "development" else logging.INFO
    fmt      = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    handlers = [logging.StreamHandler()]
    log_file = os.getenv("LOG_FILE")
    if log_file:
        handlers.append(logging.FileHandler(log_file, mode="a"))
    logging.basicConfig(level=level, format=fmt, handlers=handlers)
    logging.info(f"Logging configured at {logging.getLevelName(level)}")

def init_app_extensions(app: Quart):
    @app.before_serving
    async def startup():
        # 1) DB pool
        db_pool = await init_db_pool(app)
        app.config["DB_POOL"] = db_pool
        app.logger.info("Database pool initialized")

        # 2) Redis
        await init_redis(app)
        app.logger.info("Redis cache initialized")

        # — NO Alpaca registration here any more —
        #    It’s all handled in plugins/__init__.py

    @app.after_serving
    async def shutdown():
        app.logger.info("Beginning graceful shutdown")

        # Cancel subscriptions
        await subscription_manager.shutdown()
        app.logger.info("SubscriptionManager shut down")

        # Close plugins
        from plugins import PluginLoader
        for key in PluginLoader.list_plugins():
            try:
                plugin = PluginLoader.load_plugin(key)
                await plugin.close()
                app.logger.info(f"Plugin '{key}' closed")
            except Exception:
                app.logger.exception(f"Error closing plugin '{key}'")

        # Close WebSockets
        await close_all_ws(code=1001)
        app.logger.info("All WebSocket handlers closed")

        # Close Redis
        await close_redis(app)
        app.logger.info("Redis connection closed")

        # Close DB pool
        await close_db_pool(app)
        app.logger.info("Database pool closed")

        app.logger.info("Graceful shutdown complete")
