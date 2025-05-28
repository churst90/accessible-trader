# services/cache_manager.py

import logging
import json
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

from quart import current_app
from redis.asyncio import Redis
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from prometheus_client import Counter, REGISTRY

logger = logging.getLogger("CacheManager")
logger.debug("Starting import of services/cache_manager.py")

# Optional Prometheus metrics with duplicate prevention
try:
    if "cache_hits_total" not in [m.name for m in REGISTRY._get_names()]:
        CACHE_HITS = Counter("cache_hits_total", "Total cache hits", ["operation"])
    else:
        CACHE_HITS = REGISTRY._names_to_collectors["cache_hits_total"]

    if "cache_misses_total" not in [m.name for m in REGISTRY._get_names()]:
        CACHE_MISSES = Counter("cache_misses_total", "Total cache misses", ["operation"])
    else:
        CACHE_MISSES = REGISTRY._names_to_collectors["cache_misses_total"]

    if "cache_errors_total" not in [m.name for m in REGISTRY._get_names()]:
        CACHE_ERRORS = Counter("cache_errors_total", "Total cache errors", ["operation"])
    else:
        CACHE_ERRORS = REGISTRY._names_to_collectors["cache_errors_total"]
except (ImportError, Exception) as e:
    logger.warning(f"Failed to initialize Prometheus metrics: {e}")
    CACHE_HITS = None
    CACHE_MISSES = None
    CACHE_ERRORS = None


class Cache(ABC):
    """
    Abstract base class for cache operations.

    Defines methods for caching 1-minute and resampled OHLCV bars. Implementations handle
    storage, retrieval, and error handling for cache backends (e.g., Redis).
    """

    @abstractmethod
    async def get_1m_bars(
        self, market: str, provider: str, symbol: str, since: Optional[int], before: Optional[int], limit: int
    ) -> List[Dict[str, Any]]:
        """
        Retrieve 1-minute OHLCV bars from the cache.

        Args:
            market (str): The market identifier (e.g., "crypto", "stocks").
            provider (str): The provider identifier (e.g., "binance", "alpaca").
            symbol (str): The trading pair symbol (e.g., "BTC/USD").
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            before (Optional[int]): End timestamp in milliseconds (exclusive).
            limit (int): Maximum number of bars to return.

        Returns:
            List[Dict[str, Any]]: List of cached 1-minute OHLCV bars.
        """
        pass

    @abstractmethod
    async def store_1m_bars(
        self, market: str, provider: str, symbol: str, bars: List[Dict[str, Any]]
    ) -> None:
        """
        Store 1-minute OHLCV bars in the cache.

        Args:
            market (str): The market identifier.
            provider (str): The provider identifier.
            symbol (str): The trading pair symbol.
            bars (List[Dict[str, Any]]): List of 1-minute OHLCV bars to cache.
        """
        pass

    @abstractmethod
    async def get_resampled(self, key: str) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve resampled OHLCV bars from the cache.

        Args:
            key (str): Cache key for resampled bars (e.g., "ohlcv:crypto:binance:BTC/USD:5m").

        Returns:
            Optional[List[Dict[str, Any]]]: List of cached resampled bars, or None if not found.
        """
        pass

    @abstractmethod
    async def set_resampled(self, key: str, bars: List[Dict[str, Any]], ttl: int) -> None:
        """
        Store resampled OHLCV bars in the cache with a specified TTL.

        Args:
            key (str): Cache key for resampled bars.
            bars (List[Dict[str, Any]]): List of resampled OHLCV bars to cache.
            ttl (int): Time-to-live in seconds.
        """
        pass


class RedisCache(Cache):
    """
    Redis implementation of the Cache interface.

    Uses Redis for storing and retrieving OHLCV bars, with retries for transient errors
    and Prometheus metrics for observability.

    Attributes:
        redis (Redis): Asynchronous Redis client.
        ttl_1m (int): TTL for 1-minute bars (seconds).
        ttl_resampled (int): TTL for resampled bars (seconds).
    """

    def __init__(self, redis_client: Optional[Redis]):
        """
        Initialize the RedisCache.

        Args:
            redis_client (Optional[Redis]): Asynchronous Redis client instance.

        Raises:
            ValueError: If redis_client is None or configuration is invalid.
        """
        if redis_client is None:
            raise ValueError("Redis client must be provided")
        self.redis = redis_client
        self.ttl_1m = int(current_app.config.get("CACHE_TTL_1M_BAR_GROUP", 3600))
        self.ttl_resampled = int(current_app.config.get("CACHE_TTL_RESAMPLED_BARS", 300))
        if self.ttl_1m < 0 or self.ttl_resampled < 0:
            raise ValueError("Cache TTLs must be non-negative")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(Exception),
        after=lambda retry_state: logger.warning(
            f"Cache get_1m_bars retry attempt {retry_state.attempt_number} failed"
        ),
    )
    async def get_1m_bars(
        self, market: str, provider: str, symbol: str, since: Optional[int], before: Optional[int], limit: int
    ) -> List[Dict[str, Any]]:
        """
        Retrieve 1-minute OHLCV bars from Redis.

        Args:
            market (str): The market identifier.
            provider (str): The provider identifier.
            symbol (str): The trading pair symbol.
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            before (Optional[int]): End timestamp in milliseconds (exclusive).
            limit (int): Maximum number of bars to return.

        Returns:
            List[Dict[str, Any]]: List of cached 1-minute OHLCV bars, filtered by time range and limit.

        Raises:
            Exception: If the Redis operation fails (retried automatically).
        """
        key = f"ohlcv_1m:{market}:{provider}:{symbol}"
        try:
            # Check Redis connection
            if not self.redis:
                logger.warning("Redis client is not initialized")
                return []

            bars = await self.redis.get(key)
            if bars is None:
                logger.debug(f"Cache miss: No 1m bars found for {key}")
                if CACHE_MISSES:
                    CACHE_MISSES.labels(operation="get_1m_bars").inc()
                return []

            bars = self._deserialize_bars(bars)
            if not isinstance(bars, list):
                logger.warning(f"Invalid data format in cache for {key}: {type(bars)}")
                return []

            filtered_bars = self._filter_bars(bars, since, before, limit)
            logger.debug(f"Cache hit: Retrieved {len(filtered_bars)} 1m bars from {key}")
            if CACHE_HITS:
                CACHE_HITS.labels(operation="get_1m_bars").inc()
            return filtered_bars
        except Exception as e:
            logger.warning(f"Failed to get 1m bars from cache: {e}", exc_info=True)
            if CACHE_ERRORS:
                CACHE_ERRORS.labels(operation="get_1m_bars").inc()
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(Exception),
        after=lambda retry_state: logger.warning(
            f"Cache store_1m_bars retry attempt {retry_state.attempt_number} failed"
        ),
    )
    async def store_1m_bars(
        self, market: str, provider: str, symbol: str, bars: List[Dict[str, Any]]
    ) -> None:
        """
        Store 1-minute OHLCV bars in Redis.

        Args:
            market (str): The market identifier.
            provider (str): The provider identifier.
            symbol (str): The trading pair symbol.
            bars (List[Dict[str, Any]]): List of 1-minute OHLCV bars to cache.

        Raises:
            Exception: If the Redis operation fails (retried automatically).
        """
        if not bars:
            logger.debug("No 1m bars to store in cache")
            return
        if not self.redis:
            logger.warning("Redis client is not initialized")
            return

        key = f"ohlcv_1m:{market}:{provider}:{symbol}"
        try:
            serialized = self._serialize_bars(bars)
            await self.redis.setex(key, self.ttl_1m, serialized)
            logger.debug(f"Stored {len(bars)} 1m bars in cache at {key}")
        except Exception as e:
            logger.warning(f"Failed to store 1m bars in cache: {e}", exc_info=True)
            if CACHE_ERRORS:
                CACHE_ERRORS.labels(operation="store_1m_bars").inc()
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(Exception),
        after=lambda retry_state: logger.warning(
            f"Cache get_resampled retry attempt {retry_state.attempt_number} failed"
        ),
    )
    async def get_resampled(self, key: str) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve resampled OHLCV bars from Redis.

        Args:
            key (str): Cache key for resampled bars (e.g., "ohlcv:crypto:binance:BTC/USD:5m").

        Returns:
            Optional[List[Dict[str, Any]]]: List of cached resampled bars, or None if not found.

        Raises:
            Exception: If the Redis operation fails (retried automatically).
        """
        if not self.redis:
            logger.warning("Redis client is not initialized")
            return None

        try:
            bars = await self.redis.get(key)
            if bars is None:
                logger.debug(f"Cache miss: No resampled bars found for {key}")
                if CACHE_MISSES:
                    CACHE_MISSES.labels(operation="get_resampled").inc()
                return None

            bars = self._deserialize_bars(bars)
            if not isinstance(bars, list):
                logger.warning(f"Invalid data format in cache for {key}: {type(bars)}")
                return None

            logger.debug(f"Cache hit: Retrieved {len(bars)} resampled bars from {key}")
            if CACHE_HITS:
                CACHE_HITS.labels(operation="get_resampled").inc()
            return bars
        except Exception as e:
            logger.warning(f"Failed to get resampled bars from cache: {e}", exc_info=True)
            if CACHE_ERRORS:
                CACHE_ERRORS.labels(operation="get_resampled").inc()
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(Exception),
        after=lambda retry_state: logger.warning(
            f"Cache set_resampled retry attempt {retry_state.attempt_number} failed"
        ),
    )
    async def set_resampled(self, key: str, bars: List[Dict[str, Any]], ttl: int) -> None:
        """
        Store resampled OHLCV bars in Redis with a specified TTL.

        Args:
            key (str): Cache key for resampled bars.
            bars (List[Dict[str, Any]]): List of resampled OHLCV bars to cache.
            ttl (int): Time-to-live in seconds.

        Raises:
            Exception: If the Redis operation fails (retried automatically).
        """
        if not bars:
            logger.debug("No resampled bars to store in cache")
            return
        if not self.redis:
            logger.warning("Redis client is not initialized")
            return

        try:
            serialized = self._serialize_bars(bars)
            await self.redis.setex(key, ttl, serialized)
            logger.debug(f"Stored {len(bars)} resampled bars in cache at {key} with TTL {ttl}")
        except Exception as e:
            logger.warning(f"Failed to store resampled bars in cache: {e}", exc_info=True)
            if CACHE_ERRORS:
                CACHE_ERRORS.labels(operation="set_resampled").inc()
            raise

    def _serialize_bars(self, bars: List[Dict[str, Any]]) -> bytes:
        """
        Serialize OHLCV bars for Redis storage.

        Ensures all numeric values are JSON-serializable by converting to float and handling NaN/infinity.

        Args:
            bars (List[Dict[str, Any]]): List of OHLCV bars.

        Returns:
            bytes: Serialized data.

        Raises:
            ValueError: If bars are not in the expected format.
        """
        required_keys = {"timestamp", "open", "high", "low", "close", "volume"}
        for bar in bars:
            if not isinstance(bar, dict) or not all(k in bar for k in required_keys):
                raise ValueError(f"Invalid bar format: {bar}")
            # Ensure numeric values are JSON-serializable
            for key in ["open", "high", "low", "close", "volume"]:
                value = bar[key]
                if value is None:
                    bar[key] = 0.0
                elif not isinstance(value, (int, float)) or str(value) in ("nan", "inf", "-inf"):
                    bar[key] = 0.0
                else:
                    bar[key] = float(value)
            bar["timestamp"] = int(bar["timestamp"])  # Ensure timestamp is an integer

        try:
            return json.dumps(bars).encode("utf-8")
        except (TypeError, ValueError) as e:
            logger.error(f"Serialization failed: {e}")
            raise ValueError(f"Failed to serialize bars: {e}")

    def _deserialize_bars(self, data: bytes | str) -> List[Dict[str, Any]]: # Changed type hint here
        """
        Deserialize OHLCV bars from Redis.

        Args:
            data (bytes | str): Serialized data (expected bytes, but handle string if auto-decoded).

        Returns:
            List[Dict[str, Any]]): Deserialized list of OHLCV bars.

        Raises:
            ValueError: If deserialization fails or data is an unexpected type.
        """
        try:
            # If data is bytes, decode it first. If it's already a string, use it directly.
            if isinstance(data, bytes):
                json_string = data.decode("utf-8")
            elif isinstance(data, str):
                json_string = data
            # Added handling for None explicitly, although the caller checks for None
            elif data is None:
                logger.warning("Deserialization called with None data.")
                return []
            else:
                # Log a warning or error for unexpected types and return empty or raise
                logger.warning(f"Unexpected data type for deserialization: {type(data)}. Expected bytes or str.")
                # Depending on desired strictness, you might raise a ValueError here instead
                return []

            bars = json.loads(json_string)

            if not isinstance(bars, list):
                raise ValueError(f"Deserialized data is not a list: {type(bars)}")

            # Optional: basic validation of bar structure after deserialization
            if bars and not all(isinstance(b, dict) and "timestamp" in b for b in bars):
                logger.warning("Deserialized list contains non-dict or entries missing timestamp.")
                # Depending on strictness, might filter out bad entries or raise ValueError

            return bars

        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as e: # Added TypeError for safety
            logger.error(f"Deserialization failed due to format error: {e}", exc_info=True)
            raise ValueError(f"Failed to deserialize bars: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred during deserialization: {e}", exc_info=True)
            raise ValueError(f"Failed to deserialize bars due to unexpected error: {e}")

    def _filter_bars(
        self, bars: List[Dict[str, Any]], since: Optional[int], before: Optional[int], limit: int
    ) -> List[Dict[str, Any]]:
        """
        Filter bars by time range and limit.

        Args:
            bars (List[Dict[str, Any]]): List of OHLCV bars.
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            before (Optional[int]): End timestamp in milliseconds (exclusive).
            limit (int): Maximum number of bars to return.

        Returns:
            List[Dict[str, Any]]): Filtered list of bars.
        """
        filtered = bars
        if since is not None:
            filtered = [b for b in filtered if b["timestamp"] >= since]
        if before is not None:
            filtered = [b for b in filtered if b["timestamp"] < before]
        if len(filtered) > limit:
            filtered = filtered[-limit:] if since is None else filtered[:limit]
        return filtered

logger.debug("Finished import of services/cache_manager.py")