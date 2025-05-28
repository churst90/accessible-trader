# services/broadcast_manager.py

import logging
from typing import List, Dict, Any
from quart import Websocket

logger = logging.getLogger("BroadcastManager")


class BroadcastManager:
    """
    Responsible for sending live-update messages to a group of WebSocket subscribers
    via their per-connection send_queue.
    """
    @staticmethod
    async def broadcast(
        market: str,
        provider: str,
        symbol: str,
        timeframe: str,
        payload: Dict[str, Any],
        subscribers: List[Websocket],
    ) -> List[Websocket]:
        """
        Send a formatted JSON payload of type "update" to all subscribers.
        :returns: List of sockets that failed to receive the message.
        """
        message = {
            "type": "update",
            "symbol": symbol,
            "timeframe": timeframe,
            "payload": payload,
        }

        dead: List[Websocket] = []
        for ws in subscribers:
            try:
                queue = getattr(ws, "_send_queue", None)
                if queue:
                    await queue.put(message)
                else:
                    await ws.send_json(message)
            except Exception as e:
                logger.warning(f"BroadcastManager: failed to send to {ws}: {e}")
                dead.append(ws)

        return dead
