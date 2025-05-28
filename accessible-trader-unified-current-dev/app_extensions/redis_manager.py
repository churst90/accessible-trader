# app_extensions/redis_manager.py

import logging
from quart import Quart, current_app
import redis.asyncio as aioredis # Official async Redis client
from typing import Optional

# Import your CacheABC and RedisCache implementation
from services.cache_manager import RedisCache, Cache as CacheABC 

logger = logging.getLogger("RedisManager")

async def init_redis(app: Quart):
    """
    Initializes the asynchronous Redis client.
    The raw client is stored in app.extensions['redis_client_raw'] for general use (e.g., Pub/Sub).
    A RedisCache service instance (for caching) is also initialized using this raw client
    and stored in app.config['CACHE'] if caching is enabled.

    Args:
        app (Quart): The Quart application instance.

    Raises:
        RuntimeError: If Redis connection fails or configuration is missing.
    """
    redis_url = app.config.get("REDIS_URL")
    if not redis_url:
        logger.critical("REDIS_URL not found in app.config. Cannot initialize Redis.")
        raise RuntimeError("REDIS_URL is required for Redis connection.")

    raw_redis_client: Optional[aioredis.Redis] = None
    try:
        # Create the raw async Redis client. Connections are pooled.
        raw_redis_client = aioredis.from_url(redis_url)
        
        await raw_redis_client.ping() # Test the connection
        
        # Store the raw client directly in app.extensions for broader use (Pub/Sub, etc.)
        app.extensions["redis_client_raw"] = raw_redis_client
        logger.info(f"Raw Async Redis client connected to {redis_url} and stored in app.extensions['redis_client_raw'].")

        # Initialize and store your RedisCache service if caching is enabled
        if app.config.get("CACHE_ENABLED", True): # Assuming a config like CACHE_ENABLED
            service_cache = RedisCache(redis_client=raw_redis_client) # Pass the same raw client
            app.config["CACHE"] = service_cache 
            logger.info("RedisCache service (for caching) initialized and stored in app.config['CACHE'].")
        else:
            logger.info("Redis caching is disabled (CACHE_ENABLED=False or not set).")
            app.config["CACHE"] = None # Explicitly set to None if disabled

    except ConnectionRefusedError as e:
        logger.critical(f"Failed to connect to Redis at {redis_url}: Connection refused. Is Redis server running and accessible?", exc_info=True)
        raise RuntimeError(f"Redis connection refused at {redis_url}") from e
    except Exception as e:
        logger.critical(f"Failed to initialize Redis client or related services: {e}", exc_info=True)
        if raw_redis_client:
            try:
                await raw_redis_client.close()
                # await raw_redis_client.wait_closed() # For aioredis newer versions
            except Exception as e_close:
                logger.error(f"Error trying to close Redis client after initialization failure: {e_close}")
        raise RuntimeError(f"Redis initialization failed: {e}") from e

async def close_redis(app: Quart):
    """
    Closes the raw Redis client connection pool during application shutdown.
    This will affect all services using this client instance (e.g., RedisCache, Pub/Sub users).

    Args:
        app (Quart): The Quart application instance.
    """
    raw_redis_client: Optional[aioredis.Redis] = app.extensions.pop("redis_client_raw", None)
    
    if raw_redis_client:
        try:
            await raw_redis_client.close()
            # await raw_redis_client.wait_closed() # If using newer aioredis
            logger.info("Raw Async Redis client closed successfully.")
        except Exception as e:
            logger.error(f"Error closing raw Async Redis client: {e}", exc_info=True)
    else:
        logger.info("No raw Async Redis client found in app.extensions to close.")
    
    # app.config["CACHE"] might hold RedisCache which holds a reference to the raw client.
    # No separate close needed for app.config["CACHE"] as its underlying client is the one we just closed.
    app.config.pop("CACHE", None)


def get_raw_redis_client(quart_app: Quart = current_app) -> Optional[aioredis.Redis]:
    """
    Utility function to retrieve the raw (and shared) Redis client instance 
    from the application extensions. This client can be used for Pub/Sub.

    Args:
        quart_app (Quart, optional): The Quart application instance. Defaults to current_app.

    Returns:
        Optional[aioredis.Redis]: The raw Redis client instance, or None if not found/initialized.
    """
    try:
        client = quart_app.extensions.get("redis_client_raw")
        if not client:
            logger.warning("get_raw_redis_client: Raw Redis client not found in app.extensions. Was init_redis called?")
        return client
    except RuntimeError: 
        logger.warning("get_raw_redis_client called outside of Quart application context.")
        return None