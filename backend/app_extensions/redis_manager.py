import logging
from quart import Quart
from utils.cache import Cache

logger = logging.getLogger("RedisManager")

async def init_redis(app: Quart):
    """Initialize the Redis connection once at application startup."""
    redis_url = app.config["REDIS_URL"]
    cache = Cache(redis_url=redis_url)
    try:
        await cache.connect()
        logger.info("Redis connection initialized successfully.")
        return cache
    except Exception as e:
        logger.critical(f"Failed to initialize Redis connection: {e}")
        raise RuntimeError("Redis initialization failed.")

async def close_redis(app: Quart):
    """Close the Redis connection once during application shutdown."""
    redis_cache = get_redis(app)
    if redis_cache:
        try:
            await redis_cache.disconnect()
            logger.info("Redis connection closed successfully.")
        except Exception as e:
            logger.error(f"Error while closing Redis connection: {e}")
    else:
        logger.warning("No Redis connection to close.")

def get_redis(app: Quart):
    """
    Retrieve the Redis cache instance from the application config.
    """
    return app.config.get("CACHE")
