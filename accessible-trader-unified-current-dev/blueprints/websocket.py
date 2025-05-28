# blueprints/websocket.py

import asyncio
import logging
from typing import Optional # Added for type hinting

from quart import Blueprint, websocket, current_app, g # g for user_id context if JWT is used
from services.subscription_service import SubscriptionService # Ensure this is the updated service
from middleware.auth_middleware import get_user_from_token # Helper to optionally get user

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
    WebSocket endpoint for real-time data subscriptions.

    A single WebSocket connection can maintain multiple distinct subscriptions
    to different data streams (e.g., multiple charts, trade feeds).

    Client-to-Server Message Format (JSON):
    - Subscribe to a stream:
      {
        "action": "subscribe",
        "market": "crypto",
        "provider": "binance",
        "symbol": "BTC/USDT",
        "stream_type": "ohlcv", // "ohlcv", "trades", "order_book", "user_orders"
        "timeframe": "1m",     // Required if stream_type is "ohlcv"
        "since": 1672531200000 // Optional: for initial OHLCV history (milliseconds)
        // "user_token": "jwt_token_if_needed_for_user_orders" // Example for auth
      }
    - Unsubscribe from a specific stream:
      {
        "action": "unsubscribe",
        "market": "crypto",
        "provider": "binance",
        "symbol": "BTC/USDT",
        "stream_type": "ohlcv",
        "timeframe": "1m"      // Required if stream_type was "ohlcv"
      }
    - Ping (client can send to keep alive, server sends periodically):
      {"action": "ping"}
    - Pong (client replies to server's ping):
      {"action": "pong"}

    Server-to-Client Message Format (JSON):
    - Status/Confirmation:
      {"type": "status", "payload": {"message": "Subscribed to BTC/USDT 1m OHLCV."}}
    - Error:
      {"type": "error", "payload": {"message": "Invalid symbol."}}
    - Data Update (OHLCV example):
      {
        "type": "update", "symbol": "BTC/USDT", "timeframe": "1m",
        "payload": {"ohlc": [[ts, o, h, l, c]], "volume": [[ts, v]], "initial_batch": true/false}
      }
    - Data Update (Trade example):
      {"type": "trade_update", "symbol": "BTC/USDT", "payload": {trade_data_object}}
    - Ping (server sends periodically):
      {"type": "ping"}
    """
    ws_client = websocket._get_current_object() # Get the current WebSocket object
    # Note: Using ws_client._send_queue is a pattern that requires the writer task.
    # The SubscriptionService._send_to_websocket sends directly.
    # If you intend for SubscriptionService to also use this queue, it would need access to it.
    # For now, assuming direct send from SubscriptionService listeners and pinger uses queue.
    # Consider standardizing on one send mechanism if SubscriptionService is to use BroadcastManager.
    # For direct sending from listener tasks, this queue is only for pings from this handler.
    
    # It's good practice to have a unique ID for logging WebSocket connections if available
    ws_id_for_log = getattr(ws_client, 'id', id(ws_client))
    logger.info(f"WebSocket ({ws_id_for_log}): Connection established.")

    subscription_service: Optional[SubscriptionService] = current_app.extensions.get('subscription_service')
    if not subscription_service or not isinstance(subscription_service, SubscriptionService):
        logger.error(f"WebSocket ({ws_id_for_log}): SubscriptionService not found or incorrect type. Closing connection.")
        await ws_client.close(code=1011) # Internal server error
        return

    # --- Authentication Handling (Optional, but good for user-specific streams) ---
    # If your WebSocket connection needs to be associated with an authenticated user,
    # you might pass a token in the initial WebSocket URL (e.g., /api/ws/subscribe?token=xxx)
    # or as the first message. Here's an example if token is passed in query params:
    user_auth_token = websocket.args.get("token")
    user_info: Optional[Dict[str, Any]] = None
    if user_auth_token:
        user_info = get_user_from_token(user_auth_token) # Assuming you have this helper
        if user_info:
            logger.info(f"WebSocket ({ws_id_for_log}): Authenticated as user_id {user_info.get('id')}")
            # You can store user_info on 'g' for this WebSocket's context if needed by handlers further down,
            # but passing user_id explicitly to SubscriptionService methods is clearer.
            # g.user = user_info # Be mindful of 'g' context with WebSockets
        else:
            logger.warning(f"WebSocket ({ws_id_for_log}): Invalid token provided. Proceeding as anonymous.")
    
    current_user_id_str: Optional[str] = str(user_info.get("id")) if user_info and user_info.get("id") else None


    async def reader():
        """
        Listens for incoming messages from the WebSocket client.
        Handles 'subscribe' and 'unsubscribe' actions.
        """
        nonlocal current_user_id_str # Allow modification if an auth message comes later
        
        while True:
            try:
                message_data = await ws_client.receive_json()
                logger.debug(f"WebSocket ({ws_id_for_log}): Received message: {message_data}")
            except asyncio.CancelledError:
                logger.info(f"WebSocket ({ws_id_for_log}): Reader task cancelled.")
                break
            except json.JSONDecodeError:
                logger.warning(f"WebSocket ({ws_id_for_log}): Received invalid JSON. Ignoring.")
                # Optionally send an error message to client
                # await subscription_service._send_to_websocket(ws_client, {"type": "error", "payload": {"message": "Invalid JSON format."}})
                continue # Or break, depending on desired behavior
            except Exception as e_recv: # Catch other Quart/WebSocket connection errors
                logger.info(f"WebSocket ({ws_id_for_log}): Receive error or client disconnected: {type(e_recv).__name__} - {e_recv}. Reader terminating.")
                break

            action = message_data.get("action")

            if action == "subscribe":
                market = message_data.get("market")
                provider = message_data.get("provider")
                symbol = message_data.get("symbol")
                stream_type_str = message_data.get("stream_type")
                timeframe = message_data.get("timeframe") # Optional, but required for ohlcv
                since = message_data.get("since")       # Optional
                
                # Optional: If client sends token in a message for auth
                # client_token = message_data.get("user_token")
                # if client_token and not current_user_id_str:
                #     temp_user_info = get_user_from_token(client_token)
                #     if temp_user_info:
                #         current_user_id_str = str(temp_user_info.get("id"))
                #         logger.info(f"WebSocket ({ws_id_for_log}): Authenticated via subscribe message as user {current_user_id_str}")


                if not all([market, provider, symbol, stream_type_str]):
                    await subscription_service._send_to_websocket(ws_client, {"type": "error", "payload": {"message": "Missing required fields for subscribe: market, provider, symbol, stream_type."}})
                    continue
                
                # Call the updated SubscriptionService method
                await subscription_service.handle_subscribe_request(
                    ws=ws_client,
                    market=market,
                    provider=provider,
                    symbol=symbol,
                    requested_stream_type_str=stream_type_str,
                    requested_timeframe=timeframe,
                    since=since,
                    user_id=current_user_id_str # Pass the authenticated user_id
                )
                logger.info(f"WebSocket ({ws_id_for_log}): Processed 'subscribe' request for {market}/{provider}/{symbol} - {stream_type_str}.")

            elif action == "unsubscribe":
                market = message_data.get("market")
                provider = message_data.get("provider")
                symbol = message_data.get("symbol")
                stream_type_str = message_data.get("stream_type")
                timeframe = message_data.get("timeframe")

                if not all([market, provider, symbol, stream_type_str]):
                    await subscription_service._send_to_websocket(ws_client, {"type": "error", "payload": {"message": "Missing required fields for unsubscribe: market, provider, symbol, stream_type."}})
                    continue

                # Call the updated SubscriptionService method
                await subscription_service.handle_client_unsubscribe_message(
                    ws=ws_client,
                    market=market,
                    provider=provider,
                    symbol=symbol,
                    requested_stream_type_str=stream_type_str,
                    requested_timeframe=timeframe
                )
                logger.info(f"WebSocket ({ws_id_for_log}): Processed 'unsubscribe' request for {market}/{provider}/{symbol} - {stream_type_str}.")

            elif action in ("ping", "pong"):
                # Client might send its own pings, or reply to server pings.
                # Server also sends pings, so just log and ignore client's pings/pongs.
                logger.debug(f"WebSocket ({ws_id_for_log}): Received '{action}' heartbeat.")
                if action == "ping": # Optionally reply to client's ping with a pong
                    await subscription_service._send_to_websocket(ws_client, {"type": "pong"})

            else:
                logger.warning(f"WebSocket ({ws_id_for_log}): Received unknown action type: '{action}' in message: {message_data}")
                await subscription_service._send_to_websocket(ws_client, {"type": "error", "payload": {"message": f"Unknown action: {action}"}})
        
        logger.info(f"WebSocket ({ws_id_for_log}): Reader task finished.")


    # The writer and pinger tasks seem specific to a pattern where messages are queued
    # via ws_client._send_queue. Our SubscriptionService._redis_listener_for_client_channel
    # sends directly using ws_client.send_json() via _send_to_websocket helper.
    # If you want all server-to-client messages to go through this queue,
    # then _redis_listener_for_client_channel would need to put messages on ws_client._send_queue
    # instead of sending directly. This can be good for serializing access to the send mechanism.

    # For simplicity and directness from the listener, we'll assume direct sends for now.
    # If you keep this writer/pinger as-is, it's for messages explicitly put on ws_client._send_queue.
    # The server-side ping is good practice.

    # async def writer(): # Keep if using ws_client._send_queue extensively
    #     logger.debug(f"WebSocket ({ws_id_for_log}): Writer task started.")
    #     while True:
    #         try:
    #             message = await ws_client._send_queue.get()
    #             await ws_client.send_json(message)
    #             ws_client._send_queue.task_done()
    #         except asyncio.CancelledError:
    #             logger.info(f"WebSocket ({ws_id_for_log}): Writer task cancelled.")
    #             break
    #         except Exception as e_writer:
    #             logger.error(f"WebSocket ({ws_id_for_log}): Writer error or client disconnected: {type(e_writer).__name__}. Writer terminating.", exc_info=False)
    #             break
    #     logger.info(f"WebSocket ({ws_id_for_log}): Writer task finished.")


    async def pinger():
        """Periodically sends a 'ping' message to the client to keep connection alive."""
        ping_interval = current_app.config.get("WS_PING_INTERVAL_SEC", 30) # e.g., 30 seconds
        logger.debug(f"WebSocket ({ws_id_for_log}): Pinger task started with interval {ping_interval}s.")
        while True:
            try:
                await asyncio.sleep(ping_interval)
                # Use the direct send method for pings as well, for consistency with listeners.
                # Or, if using the queue pattern, put it on the queue.
                if not await subscription_service._send_to_websocket(ws_client, {"type": "ping"}):
                    logger.info(f"WebSocket ({ws_id_for_log}): Failed to send ping, client likely gone. Pinger terminating.")
                    break
                logger.debug(f"WebSocket ({ws_id_for_log}): Sent ping.")
            except asyncio.CancelledError:
                logger.info(f"WebSocket ({ws_id_for_log}): Pinger task cancelled.")
                break
            except Exception as e_pinger: # Should not happen if _send_to_websocket handles errors
                logger.error(f"WebSocket ({ws_id_for_log}): Unexpected error in pinger: {e_pinger}. Pinger terminating.", exc_info=True)
                break
        logger.info(f"WebSocket ({ws_id_for_log}): Pinger task finished.")

    # Create and run tasks
    reader_task = asyncio.create_task(reader(), name=f"ws-reader-{ws_id_for_log}")
    # writer_task = asyncio.create_task(writer(), name=f"ws-writer-{ws_id_for_log}") # If using send_queue pattern
    ping_task   = asyncio.create_task(pinger(), name=f"ws-pinger-{ws_id_for_log}")

    # tasks_to_wait_for = {reader_task, writer_task, ping_task} # If using writer
    tasks_to_wait_for = {reader_task, ping_task}


    # Wait for any of the main tasks to complete (e.g., reader if client disconnects)
    done, pending = await asyncio.wait(
        tasks_to_wait_for,
        return_when=asyncio.FIRST_COMPLETED,
    )

    logger.info(f"WebSocket ({ws_id_for_log}): One of the main tasks completed. Cleaning up pending tasks.")
    for task in pending:
        if not task.done():
            task.cancel()
            # Optionally await task here with a timeout if needed, but cancellation should be enough
            # try:
            #     await asyncio.wait_for(task, timeout=1.0)
            # except asyncio.TimeoutError:
            #     logger.warning(f"WebSocket ({ws_id_for_log}): Task {task.get_name()} did not cancel in time.")
            # except asyncio.CancelledError:
            #     pass # Expected

    # Ensure all tasks are awaited to prevent "Task exception was never retrieved"
    # if they raise something other than CancelledError on cancellation.
    if tasks_to_wait_for: # Check if the set is not empty
        await asyncio.gather(*tasks_to_wait_for, return_exceptions=True)


    # --- Final Cleanup on WebSocket Closure ---
    # This is called when the WebSocket connection handling is ending,
    # typically because the client disconnected or an unrecoverable error occurred in the reader.
    logger.info(f"WebSocket ({ws_id_for_log}): Connection handling ending. Performing final cleanup for all subscriptions of this client.")
    # Use the method designed for full client disconnect cleanup
    await subscription_service.handle_client_disconnect(ws_client)
    logger.info(f"WebSocket ({ws_id_for_log}): Connection closed and all subscriptions cleaned up.")