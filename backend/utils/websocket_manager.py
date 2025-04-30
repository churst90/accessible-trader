import asyncio
import logging

logger = logging.getLogger("WebSocketManager")

class WebSocketManager:
    def __init__(self):
        """
        Initialize WebSocketManager with a set of active WebSocket connections.
        """
        self.connections = set()
        self.lock = asyncio.Lock()  # Protect access to the connections set

    async def add_connection(self, websocket):
        """
        Add a WebSocket connection to the connection pool.
        """
        async with self.lock:
            self.connections.add(websocket)
            logger.info(f"WebSocket connection added. Total connections: {len(self.connections)}")

    async def remove_connection(self, websocket):
        """
        Remove a WebSocket connection from the connection pool.
        """
        async with self.lock:
            if websocket in self.connections:
                self.connections.remove(websocket)
                logger.info(f"WebSocket connection removed. Total connections: {len(self.connections)}")

    async def broadcast(self, message):
        """
        Send a message to all active WebSocket connections.
        """
        async with self.lock:
            if not self.connections:
                logger.warning("No active WebSocket connections to broadcast to.")
                return

            stale_connections = set()
            for connection in self.connections:
                try:
                    await connection.send_json(message)
                    logger.debug(f"Broadcasted message to connection: {connection}")
                except Exception as e:
                    logger.error(f"Error broadcasting to WebSocket: {e}")
                    stale_connections.add(connection)

            # Remove stale connections
            for stale_connection in stale_connections:
                await self.remove_connection(stale_connection)

            if stale_connections:
                logger.info(f"Removed {len(stale_connections)} stale WebSocket connections.")

    async def close_all(self):
        """
        Close all WebSocket connections gracefully.
        """
        async with self.lock:
            logger.info("Closing all WebSocket connections.")
            for connection in list(self.connections):
                try:
                    await connection.close()
                except Exception as e:
                    logger.error(f"Error closing WebSocket connection: {e}")
                finally:
                    self.connections.discard(connection)
            logger.info("All WebSocket connections closed.")
