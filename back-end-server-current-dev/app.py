# app.py

import logging
from quart import Quart, jsonify
from quart_cors import cors

from config import config_class, ConfigError
from app_extensions import configure_logging, init_app_extensions
from blueprints import init_blueprints
from middleware.error_handler import init_error_handlers

def create_app() -> Quart:
    # -- Create & configure app --
    app = Quart(__name__)

    # --- Validate environment & required secrets now (fail fast) ---
    try:
        config_class.validate()
    except ConfigError as e:
        raise RuntimeError(f"Configuration error: {e}")

    app.config.from_object(config_class)

    # -- Logging --
    configure_logging(app)

    # -- Init extensions (DB, Redis) --
    init_app_extensions(app)

    # -- CORS --
    trusted = app.config.get("TRUSTED_ORIGINS") or ["*"]
    cors(app, allow_origin=trusted)

    # -- Blueprints & Error Handlers --
    init_blueprints(app)
    init_error_handlers(app)

    # -- Health check endpoint --
    @app.route("/health", methods=["GET"])
    async def health():
        from app_extensions.db_pool import get_pool
        from app_extensions.redis_manager import get_redis

        try:
            pool = get_pool(app)
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_status = "ok"
        except Exception:
            db_status = "unavailable"

        try:
            cache = get_redis(app)
            pong  = await cache.redis.ping()
            redis_status = "ok" if pong else "unavailable"
        except Exception:
            redis_status = "unavailable"

        return jsonify({
            "status":   "ok",
            "database": db_status,
            "redis":    redis_status
        }), 200

    return app
