# services/ws_registry.py

import asyncio
import logging
from typing import Set
from quart import Websocket

logger = logging.getLogger("WebSocketRegistry")

# Global active WebSocket set
ACTIVE_SOCKETS: Set[Websocket] = set()
_REGISTRY_LOCK = asyncio.Lock()


async def register(ws: Websocket) -> None:
    """Register a new active WebSocket connection."""
    async with _REGISTRY_LOCK:
        ACTIVE_SOCKETS.add(ws)
        logger.info(f"WebSocket registered. Active count: {len(ACTIVE_SOCKETS)}")


async def unregister(ws: Websocket) -> None:
    """Unregister a WebSocket connection that is closing."""
    async with _REGISTRY_LOCK:
        ACTIVE_SOCKETS.discard(ws)
        logger.info(f"WebSocket unregistered. Active count: {len(ACTIVE_SOCKETS)}")


async def close_all(code: int = 1001) -> None:
    """
    Close all active WebSockets cleanly with the given close code.
    This is called during server shutdown.
    """
    async with _REGISTRY_LOCK:
        sockets = list(ACTIVE_SOCKETS)
        ACTIVE_SOCKETS.clear()

    logger.info(f"Closing {len(sockets)} active WebSocket connections...")

    for ws in sockets:
        try:
            await ws.close(code=code)
        except Exception as e:
            logger.warning(f"WebSocket close error: {e}")

    logger.info("All active WebSockets closed.")
