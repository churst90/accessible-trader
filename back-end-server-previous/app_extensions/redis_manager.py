# app_extensions/redis_manager.py

import logging
from quart import Quart
import redis.asyncio as aioredis # Import for the raw client
from services.cache_manager import RedisCache, Cache as CacheABC # Use the new RedisCache and its ABC

logger = logging.getLogger("RedisManager")

async def init_redis(app: Quart):
    """
    Initialize the Redis cache (services.cache_manager.RedisCache) once at application startup.
    """
    redis_url = app.config["REDIS_URL"]
    raw_redis_client = None
    try:
        # Create the raw asyncpg Redis client
        raw_redis_client = aioredis.from_url(redis_url) # No decode_responses=True, RedisCache handles bytes/str
        await raw_redis_client.ping() # Test connection
        logger.info(f"Raw Redis client connected to {redis_url}")

        # Initialize our RedisCache service with the raw client
        service_cache = RedisCache(redis_client=raw_redis_client)
        app.config["CACHE"] = service_cache # Store services.cache_manager.RedisCache instance
        logger.info("RedisCache service initialized and stored in app.config['CACHE'].")

    except Exception as e:
        logger.critical(f"Failed to initialize Redis or RedisCache service: {e}", exc_info=True)
        if raw_redis_client:
            await raw_redis_client.close() # Ensure raw client is closed on error
        raise

async def close_redis(app: Quart):
    """
    Close the Redis cache (services.cache_manager.RedisCache) at application shutdown.
    This will also close the underlying raw Redis client.
    """
    cache_service = app.config.get("CACHE")
    if cache_service and isinstance(cache_service, RedisCache):
        try:
            # RedisCache.redis is the raw client; closing it directly or via a method if RedisCache had one.
            # Assuming RedisCache doesn't have its own close method, close its internal client.
            if cache_service.redis:
                await cache_service.redis.close()
                logger.info("Raw Redis client within RedisCache service closed.")
        except Exception as e:
            logger.error(f"Error closing Redis client from RedisCache service: {e}", exc_info=True)
    elif cache_service: # If it's some other cache object
        logger.warning("app.config['CACHE'] is not a RedisCache instance. Attempting generic close if available.")
        if hasattr(cache_service, 'disconnect'): # For old utils.cache.Cache if somehow still present
            await cache_service.disconnect()
        elif hasattr(cache_service, 'close'):
             await cache_service.close()
    else:
        logger.warning("No Redis cache service found in app.config to close.")

def get_redis(app: Quart) -> CacheABC: # Return type is now the services.cache_manager.Cache ABC
    """
    Retrieve the Cache service instance (should be RedisCache).
    """
    cache_instance = app.config.get("CACHE")
    if not isinstance(cache_instance, CacheABC):
        logger.warning(f"CACHE in app.config is not an instance of services.cache_manager.Cache. Found: {type(cache_instance)}")
        # Depending on strictness, could raise an error here or return None
    return cache_instance