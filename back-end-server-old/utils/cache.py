# utils/cache.py

import json
import logging
import redis.asyncio as aioredis  # note: now redis.asyncio

logger = logging.getLogger("Cache")

class Cache:
    def __init__(self, redis_url: str = "redis://localhost"):
        """
        Initialize the Cache with a Redis connection URL.
        Connection happens in connect().
        """
        self.redis_url = redis_url
        self.redis = None

    async def connect(self):
        """
        Establish the Redis connection.
        """
        if not self.redis:
            try:
                # Use redis.asyncio.from_url(...)
                self.redis = aioredis.from_url(self.redis_url, decode_responses=True)
                # Test it
                await self.redis.ping()
                logger.info(f"Connected to Redis at {self.redis_url}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis at {self.redis_url}: {e}")
                self.redis = None
                raise

    async def disconnect(self):
        """
        Close the Redis connection.
        """
        if self.redis:
            try:
                await self.redis.close()
                logger.info("Redis connection closed.")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}")
            finally:
                self.redis = None

    async def get(self, key: str):
        """
        Retrieve a JSON-encoded value by key.
        """
        if not self.redis:
            raise RuntimeError("Redis connection not established.")
        try:
            raw = await self.redis.get(key)
            if raw is None:
                logger.debug(f"Cache miss for key: {key}")
                return None
            logger.debug(f"Cache hit for key: {key}")
            return json.loads(raw)
        except Exception as e:
            logger.error(f"Error getting key '{key}' from cache: {e}")
            return None

    async def set(self, key: str, value, expire: int = 300):
        """
        Store a JSON-serializable value under key with expiration (seconds).
        """
        if not self.redis:
            raise RuntimeError("Redis connection not established.")
        try:
            payload = json.dumps(value)
            await self.redis.set(name=key, value=payload, ex=expire)
            logger.debug(f"Key '{key}' set in cache for {expire}s.")
        except Exception as e:
            logger.error(f"Error setting key '{key}' in cache: {e}")
            raise

    async def delete(self, key: str):
        """
        Remove a key from cache.
        """
        if not self.redis:
            raise RuntimeError("Redis connection not established.")
        try:
            deleted = await self.redis.delete(key)
            logger.debug(f"Key '{key}' deleted: {bool(deleted)}")
        except Exception as e:
            logger.error(f"Error deleting key '{key}': {e}")

    async def flush(self):
        """
        Flush the entire Redis database.
        """
        if not self.redis:
            raise RuntimeError("Redis connection not established.")
        try:
            await self.redis.flushdb()
            logger.info("Redis cache flushed.")
        except Exception as e:
            logger.error(f"Error flushing Redis cache: {e}")
            raise
