import aioredis
import json
import logging

logger = logging.getLogger("Cache")

class Cache:
    def __init__(self, redis_url="redis://localhost"):
        """
        Initialize the Cache with a Redis connection URL.
        Note that actual connection is established when connect() is called.
        """
        self.redis_url = redis_url
        self.redis = None

    async def connect(self):
        if not self.redis:
            try:
                self.redis = aioredis.from_url(self.redis_url)
                await self.redis.ping()
                logger.info(f"Connected to Redis at {self.redis_url}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis at {self.redis_url}: {e}")
                raise ValueError("Redis connection is not established.")

    async def disconnect(self):
        if self.redis:
            try:
                await self.redis.close()
                logger.info("Redis connection closed.")
                self.redis = None
            except Exception as e:
                logger.error(f"Error while closing Redis connection: {e}")

    async def get(self, key):
        if not self.redis:
            raise ValueError("Redis connection is not established.")
        try:
            data = await self.redis.get(key)
            if data:
                logger.debug(f"Cache hit for key: {key}")
                return json.loads(data)
            logger.debug(f"Cache miss for key: {key}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON for key {key}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving key '{key}' from cache: {e}")
            raise ValueError(f"Cache get operation failed: {e}")

    async def set(self, key, value, expire=300):
        if not self.redis:
            raise ValueError("Redis connection is not established.")
        try:
            await self.redis.set(key, json.dumps(value), ex=expire)
            logger.debug(f"Key '{key}' stored in cache with expiration: {expire} seconds.")
        except Exception as e:
            logger.error(f"Error setting key '{key}' in cache: {e}")
            raise ValueError(f"Cache set operation failed: {e}")

    async def delete(self, key):
        if not self.redis:
            raise ValueError("Redis connection is not established.")
        try:
            result = await self.redis.delete(key)
            if result:
                logger.debug(f"Key '{key}' deleted from cache.")
            else:
                logger.debug(f"Key '{key}' not found in cache.")
        except Exception as e:
            logger.error(f"Error deleting key '{key}' from cache: {e}")
            raise ValueError(f"Cache delete operation failed: {e}")

    async def flush(self):
        if not self.redis:
            raise ValueError("Redis connection is not established.")
        try:
            await self.redis.flushdb()
            logger.info("All keys flushed from Redis cache.")
        except Exception as e:
            logger.error(f"Error flushing Redis cache: {e}")
            raise ValueError(f"Cache flush operation failed: {e}")
