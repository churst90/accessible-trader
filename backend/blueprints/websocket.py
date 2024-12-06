from quart import Blueprint, websocket
from services.websocket_service import WebSocketService

websocket_blueprint = Blueprint("websocket_blueprint", __name__, url_prefix="/ws")

@websocket_blueprint.websocket("/subscribe")
async def subscribe():
    """
    WebSocket endpoint to subscribe to realtime market data.
    """
    market = websocket.args.get("market")
    symbols = websocket.args.get("symbols", "").split(",")

    if not market or not symbols:
        await websocket.send_json({"success": False, "error": "Market and symbols are required."})
        return

    service = WebSocketService(market)
    await service.handle_subscription(websocket, symbols)
