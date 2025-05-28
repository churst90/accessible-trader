# services/subscription_lock.py
# Manages per-subscription asyncio locks to prevent concurrent poll loops

import asyncio
from typing import Tuple, Dict

# Global lock store keyed by (market, provider, symbol, timeframe)
_locks: Dict[Tuple[str, str, str, str], asyncio.Lock] = {}

class SubscriptionLock:
    """
    Provides a named asyncio.Lock for each unique subscription (market/provider/symbol/timeframe).
    Ensures that at most one polling loop runs per subscription key.
    """
    @staticmethod
    def _key(market: str, provider: str, symbol: str, timeframe: str) -> Tuple[str, str, str, str]:
        return (market, provider, symbol, timeframe)

    @classmethod
    async def acquire(
        cls,
        market: str,
        provider: str,
        symbol: str,
        timeframe: str
    ) -> None:
        """
        Acquire (or create+acquire) the lock for the given subscription key.
        This will block if another poll loop is active.
        """
        key = cls._key(market, provider, symbol, timeframe)
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        await lock.acquire()

    @classmethod
    def release(
        cls,
        market: str,
        provider: str,
        symbol: str,
        timeframe: str
    ) -> None:
        """
        Release the lock for the given subscription key, if held.
        """
        key = cls._key(market, provider, symbol, timeframe)
        lock = _locks.get(key)
        if lock and lock.locked():
            lock.release()

    @classmethod
    def is_locked(
        cls,
        market: str,
        provider: str,
        symbol: str,
        timeframe: str
    ) -> bool:
        """
        Check whether the lock for the subscription key is currently held.
        """
        key = cls._key(market, provider, symbol, timeframe)
        lock = _locks.get(key)
        return lock.locked() if lock else False
