import asyncio
from plugins import load_market_plugin
from utils.websocket_manager import WebSocketManager
import logging

logger = logging.getLogger("WebSocketService")


class WebSocketService:
    def __init__(self, market):
        """
        Initialize WebSocketService for the specified market.
        """
        try:
            self.plugin = load_market_plugin(market)
            self.websocket_manager = WebSocketManager()
        except ValueError as e:
            logger.error(f"Market '{market}' is not supported: {e}")
            raise ValueError(f"Market '{market}' is not supported")

    async def handle_subscription(self, websocket, symbols):
        """
        Manage WebSocket subscriptions and broadcast data to the client.
        """
        logger.info(f"WebSocket connection established for symbols: {symbols}")
        try:
            # Register the WebSocket connection
            self.websocket_manager.add_connection(websocket)

            # Callback for broadcasting updates
            async def broadcast_update(ticker):
                logger.debug(f"Broadcasting ticker update: {ticker}")
                await self.websocket_manager.broadcast(ticker)

            # Subscribe to ticker updates via the plugin
            await self.plugin.subscribe_to_ticker(symbols=symbols, callback=broadcast_update)
        except asyncio.CancelledError:
            logger.info("WebSocket subscription task canceled.")
        except Exception as e:
            logger.error(f"Error during WebSocket subscription: {e}")
            await websocket.send_json({"success": False, "error": str(e)})
        finally:
            # Ensure WebSocket connection is properly removed
            self.websocket_manager.remove_connection(websocket)
            logger.info("WebSocket connection closed.")

    async def broadcast_to_all(self, message):
        """
        Broadcast a custom message to all connected WebSocket clients.
        """
        try:
            logger.debug(f"Broadcasting custom message: {message}")
            await self.websocket_manager.broadcast(message)
        except Exception as e:
            logger.error(f"Error broadcasting message to clients: {e}")
