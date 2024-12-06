from quart import Quart, jsonify
from quart_cors import cors
from app_extensions import init_app_extensions
from blueprints import init_blueprints
from middleware.error_handler import init_error_handlers
import os
import logging
from config import config_class
from typing import Any

def create_app():
    """Create and configure the Quart application."""
    app = Quart(__name__)

    # Load configuration into app.config
    app.config.from_object(config_class)

    # Configure CORS using app.config["TRUSTED_ORIGINS"]
    trusted_origins = app.config["TRUSTED_ORIGINS"]
    app = cors(app, allow_origin=trusted_origins if trusted_origins else "*")

    # Initialize all extensions (database, Redis, logging)
    init_app_extensions(app)

    # Register blueprints (routes/endpoints)
    init_blueprints(app)

    # Register error handlers
    init_error_handlers(app)

    # Health check route
    @app.route("/health", methods=["GET"])
    async def health():
        """Enhanced health check endpoint."""
        try:
            db_status = "ok" if await check_database(app) else "unavailable"
            redis_status = "ok" if await check_redis(app) else "unavailable"
            return jsonify({"status": "ok", "database": db_status, "redis": redis_status}), 200
        except Exception as e:
            logging.error(f"Health check failed: {str(e)}")
            return jsonify({"status": "error", "details": str(e)}), 500

    return app

async def check_database(app: Quart) -> bool:
    """Simple function to check database connectivity."""
    # Will later refer to db pool via app.config instead of global
    from app_extensions.db_pool import get_pool
    pool = get_pool(app)
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception as e:
        logging.error(f"Database check failed: {str(e)}")
        return False

async def check_redis(app: Quart) -> bool:
    """Simple function to check Redis connectivity."""
    from app_extensions.redis_manager import get_redis
    cache = get_redis(app)
    try:
        pong = await cache.redis.ping()
        return pong is not None
    except Exception as e:
        logging.error(f"Redis check failed: {str(e)}")
        return False
