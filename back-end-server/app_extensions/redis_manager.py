# app_extensions/redis_manager.py

import logging
from quart import Quart
from utils.cache import Cache

logger = logging.getLogger("RedisManager")

async def init_redis(app: Quart):
    """
    Initialize the Redis cache once at application startup.
    """
    redis_url = app.config["REDIS_URL"]
    cache = Cache(redis_url=redis_url)
    try:
        await cache.connect()
        app.config["CACHE"] = cache
        logger.info("Redis cache initialized and stored in app.config['CACHE'].")
    except Exception as e:
        logger.critical(f"Failed to initialize Redis: {e}")
        raise

async def close_redis(app: Quart):
    """
    Close the Redis cache at application shutdown.
    """
    cache = app.config.get("CACHE")
    if cache:
        try:
            await cache.disconnect()
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")
    else:
        logger.warning("No Redis cache to close.")

def get_redis(app: Quart) -> Cache:
    """
    Retrieve the Cache instance.
    """
    return app.config.get("CACHE")
