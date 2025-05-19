import asyncio
import logging

from quart import Blueprint, websocket, current_app
from services.subscription_service import SubscriptionService

logger = logging.getLogger("WebSocketBlueprint")

# mount this blueprint at /api/ws
websocket_blueprint = Blueprint(
    "websocket",
    __name__,
    url_prefix="/api/ws"
)


@websocket_blueprint.websocket("/subscribe")
async def ws_handler():
    """
    WebSocket endpoint for chart data.
    
    - client sends {"type":"subscribe", market, provider, symbol, timeframe, since}
      ? we backfill + send historical bars, then register for live updates
    - client sends {"type":"unsubscribe"} ? we tear down the live feed
    - client may reply {"type":"pong"} (or even {"type":"ping"}) for heartbeats
      ? we simply ignore those
    """
    ws = websocket._get_current_object()
    # attach a per-connection send-queue
    ws._send_queue = asyncio.Queue()

    subscription_service = current_app.extensions.get('subscription_service')
    if not subscription_service:
        logger.error("SubscriptionService not found in app extensions. Cannot handle WebSocket.")
        await websocket.close(1011) # Internal server error
        return

    async def reader():
        while True:
            try:
                msg = await websocket.receive_json()
            except asyncio.CancelledError:
                break
            except Exception:
                # client disconnected or sent invalid JSON
                break

            typ = msg.get("type")
            if typ == "subscribe":
                await subscription_service.subscribe(
                    market=msg["market"],
                    provider=msg["provider"],
                    symbol=msg["symbol"],
                    timeframe=msg["timeframe"],
                    since=msg.get("since"),
                )
                logger.info(f"Subscribed {ws} ? {msg}")

            elif typ == "unsubscribe":
                await subscription_service.unsubscribe_current()
                logger.info(f"Unsubscribed {ws}")

            elif typ in ("ping", "pong"):
                # Heartbeat messages—just ignore
                continue

            else:
                # anything unexpected is still worth a debug
                logger.debug(f"Unknown WS message type: {msg}")

    async def writer():
        # Drain the send-queue and push out on the real socket
        while True:
            message = await ws._send_queue.get()
            try:
                await websocket.send_json(message)
            except Exception:
                break  # socket gone or error

    async def pinger():
        interval = current_app.config.get("WS_PING_INTERVAL_SEC", 10)
        while True:
            await asyncio.sleep(interval)
            try:
                # send via the queue so it won't conflict with background broadcasts
                await ws._send_queue.put({"type": "ping"})
            except Exception:
                break  # socket gone

    # Run reader + writer + pinger until any exits
    reader_task = asyncio.create_task(reader(), name="ws-reader")
    writer_task = asyncio.create_task(writer(), name="ws-writer")
    ping_task   = asyncio.create_task(pinger(), name="ws-pinger")

    done, pending = await asyncio.wait(
        {reader_task, writer_task, ping_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()

    # clean up any live subscription
    await subscription_service.unsubscribe_current()
    logger.info("WebSocket connection closed.")
