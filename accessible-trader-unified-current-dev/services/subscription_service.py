# services/subscription_service.py

import asyncio
import logging
import json # For message deserialization from Redis
from typing import Optional, Dict, Any, List, Set, cast, Tuple, Union

from quart import websocket, current_app, g # g for user_id context if needed
from redis.asyncio import Redis as AsyncRedis
from redis.asyncio.client import PubSub as AsyncPubSub
import redis.exceptions as redis_exceptions # For specific Redis exceptions

from plugins.base import PluginError, OHLCVBar # OHLCVBar for historical data type hint
from services.market_service import MarketService
# Uses the revised SubscriptionRegistry that supports multiple keys per WebSocket
from services.subscription_registry import SubscriptionRegistry, SubscriptionKey
from services.streaming_manager import StreamingManager, StreamType, StreamKey as ManagerStreamKey

logger = logging.getLogger(__name__) # Or "SubscriptionService"

# Type alias for Quart's WebSocket object for clarity
WebSocketClient = Any # from quart.wrappers.websocket import Websocket is the actual type

class SubscriptionService:
    """
    Coordinates WebSocket client subscriptions for real-time market data using Redis Pub/Sub.
    This service allows a single WebSocket client to maintain multiple distinct subscriptions
    to different data streams simultaneously (e.g., multiple charts, trade feeds).

    Responsibilities:
    - Manages client WebSocket connections and their specific data view subscriptions.
      Each distinct subscription (e.g., BTC/USDT 1m OHLCV) from a client is a "view".
    - For each client view:
        - Fetches and sends initial historical data if applicable (e.g., for OHLCV charts).
        - Instructs `StreamingManager` to ensure the underlying exchange data stream is active.
          `StreamingManager` then publishes data from the plugin to a relevant Redis channel.
        - Manages a dedicated `asyncio.Task` that listens to that specific Redis Pub/Sub channel.
        - This listener task forwards formatted data from Redis to the client for that view.
    - Handles client requests to unsubscribe from specific views.
    - Ensures proper cleanup of all resources (listeners, registry entries, StreamingManager
      references) when a client disconnects or unsubscribes.
    """

    def __init__(
        self,
        market_service_instance: MarketService,
        streaming_manager_instance: StreamingManager,
        redis_client: AsyncRedis
    ):
        """
        Initializes the SubscriptionService.

        Args:
            market_service_instance (MarketService): Instance for fetching historical data
                                                     and plugin details.
            streaming_manager_instance (StreamingManager): Instance for managing underlying
                                                           plugin data streams and Redis publishing.
            redis_client (AsyncRedis): Raw asynchronous Redis client instance for Pub/Sub.
        """
        if not isinstance(market_service_instance, MarketService):
            raise TypeError("SubscriptionService requires a valid MarketService instance.")
        if not isinstance(streaming_manager_instance, StreamingManager):
            raise TypeError("SubscriptionService requires a valid StreamingManager instance.")
        if not isinstance(redis_client, AsyncRedis):
            # Allow for duck typing if a compatible proxy is used, but AsyncRedis is expected.
            # Consider isinstance(redis_client, (AsyncRedis, YourRedisProxy)) if applicable.
             logger.warning("SubscriptionService initialized with a redis_client not of type redis.asyncio.Redis. Compatibility assumed.")
        # Re-enable strict check if direct type is guaranteed:
        # if not isinstance(redis_client, AsyncRedis):
        # raise TypeError("SubscriptionService requires a valid redis.asyncio.Redis client instance.")


        # Use the revised SubscriptionRegistry that supports multiple SubscriptionKeys per WebSocket.
        self._registry = SubscriptionRegistry()
        self.market_service: MarketService = market_service_instance
        self.streaming_manager: StreamingManager = streaming_manager_instance
        self.redis_client: AsyncRedis = redis_client

        # Tracks active Redis listener tasks for each WebSocket client, per Redis channel.
        # Structure: ws_client -> {redis_channel_name (str): asyncio.Task}
        self._client_channel_listeners: Dict[WebSocketClient, Dict[str, asyncio.Task]] = {}

        # Maps a client's requested view (SubscriptionKey) to the actual Redis channel name.
        # Structure: ws_client -> {client_view_key (SubscriptionKey): redis_channel_name (str)}
        self._client_view_to_redis_channel: Dict[WebSocketClient, Dict[SubscriptionKey, str]] = {}

        # Maps a client's requested view (SubscriptionKey) to the StreamKey used by StreamingManager.
        # Crucial for accurately releasing streams in StreamingManager.
        # Structure: ws_client -> {client_view_key (SubscriptionKey): manager_stream_key (ManagerStreamKey)}
        self._client_view_to_manager_key: Dict[WebSocketClient, Dict[SubscriptionKey, ManagerStreamKey]] = {}

        # Stores user_id context if a specific client view is for USER_ORDERS, needed for release.
        # Structure: ws_client -> {client_view_key_for_user_orders (SubscriptionKey): user_id (str)}
        self._client_user_order_contexts: Dict[WebSocketClient, Dict[SubscriptionKey, str]] = {}

        logger.info("SubscriptionService initialized (Multi-Subscription-Per-Client Model).")

    @staticmethod
    async def _send_to_websocket(ws: WebSocketClient, message: Dict[str, Any]) -> bool:
        """
        Helper method to safely send a JSON message to a single WebSocket client.

        Args:
            ws (WebSocketClient): The WebSocket client connection object.
            message (Dict[str, Any]): The message dictionary to send (will be JSON serialized).

        Returns:
            bool: True if the message was sent (or queued) successfully, False if an error
                  occurred (e.g., client disconnected, task cancelled).
        """
        try:
            await ws.send_json(message)
            return True
        except asyncio.CancelledError: # Specific check for task cancellation
            # This can happen if the WebSocket connection task itself is being cancelled.
            logger.warning(f"SubSvc _send_to_websocket: Send operation cancelled for WS {getattr(ws, 'id', id(ws))}.")
            return False
        except Exception as e: # Catch other common WebSocket errors
            # Common errors include ConnectionClosedOK, ConnectionClosedError from Quart/Hypercorn
            # if the client has already disconnected.
            ws_id_for_log = getattr(ws, 'id', id(ws))
            logger.warning(
                f"SubSvc _send_to_websocket: Error sending to WS {ws_id_for_log}: {type(e).__name__}. Client likely disconnected or send error: {str(e)[:100]}",
                exc_info=False # Set to True for full traceback if needed, but can be noisy for common disconnects.
            )
            return False

    async def _redis_listener_for_client_channel(
        self,
        ws: WebSocketClient,
        client_view_key: SubscriptionKey, # The specific view this listener is for
        redis_channel_name: str           # The Redis channel it listens to
    ):
        """
        Dedicated asyncio task for a WebSocket client to listen to a specific Redis Pub/Sub channel,
        corresponding to one of their active subscriptions (a "view").

        It receives messages published by StreamingManager (which originate from plugins)
        and forwards formatted updates relevant to this specific `client_view_key`
        to the WebSocket client.

        Args:
            ws (WebSocketClient): The WebSocket client connection.
            client_view_key (SubscriptionKey): The specific (market, provider, symbol, tf_or_type)
                                               view this listener serves for the client.
            redis_channel_name (str): The Redis Pub/Sub channel to subscribe to.
        """
        ws_id_for_log = getattr(ws, 'id', id(ws))
        log_prefix = f"RedisListener (WS:{ws_id_for_log}, View:{client_view_key}, RedisChan:{redis_channel_name}):"
        logger.info(f"{log_prefix} Starting listener task.")

        pubsub_client: Optional[AsyncPubSub] = None
        try:
            # Create a new PubSub object for each listener task to ensure isolation.
            pubsub_client = self.redis_client.pubsub(ignore_subscribe_messages=True)
            await pubsub_client.subscribe(redis_channel_name)
            logger.info(f"{log_prefix} Successfully subscribed to Redis channel '{redis_channel_name}'.")

            while True:
                # Gracefully exit if the task is cancelled (e.g., during unsubscription or shutdown).
                if asyncio.current_task().cancelled(): # type: ignore[attr-defined]
                    logger.info(f"{log_prefix} Cancellation requested, exiting listen loop.")
                    break

                message = None
                try:
                    # Listen for new messages with a timeout to allow periodic cancellation checks.
                    message = await pubsub_client.get_message(timeout=1.0)
                except redis_exceptions.ConnectionError as e_redis_conn:
                    logger.error(f"{log_prefix} Redis connection error during get_message: {e_redis_conn}. Listener stopping.", exc_info=True)
                    break # Stop this listener if Redis connection is lost. Reconnection handled by redis client itself or app restart.
                except asyncio.TimeoutError: # Should be caught by get_message returning None with timeout.
                    continue # No message, loop to check for cancellation or next message.
                except Exception as e_get_msg: # Catch any other unexpected error from get_message
                    logger.error(f"{log_prefix} Unexpected error from get_message: {e_get_msg}. Listener stopping.", exc_info=True)
                    break


                if message is None:
                    continue # Timeout, no message received.

                if message["type"] == "message":
                    try:
                        message_content_str = message["data"].decode('utf-8')
                        # Data from Redis, published by StreamingManager._handle_plugin_message
                        data_from_redis = json.loads(message_content_str)

                        # Extract details from the client_view_key this listener is for.
                        # This ensures we only process/format data relevant to THIS specific subscription view.
                        _view_market, _view_provider, view_symbol_for_client, view_tf_or_type_for_client = client_view_key

                        # The payload from Redis should contain 'stream_type', 'symbol', etc.,
                        # as added by StreamingManager._handle_plugin_message.
                        payload_stream_type_str = data_from_redis.get("stream_type")
                        if not payload_stream_type_str:
                            logger.warning(f"{log_prefix} 'stream_type' missing in Redis message: {data_from_redis}")
                            continue
                        try:
                            stream_type_from_payload = StreamType(payload_stream_type_str)
                        except ValueError:
                            logger.warning(f"{log_prefix} Invalid 'stream_type' value '{payload_stream_type_str}' in Redis message. Discarding.")
                            continue

                        client_message_to_send: Optional[Dict[str, Any]] = None

                        # --- Message Formatting and Filtering Logic ---
                        # Construct the message for the client IF the data_from_redis matches
                        # the specifics of what this client_view_key represents.
                        # Example: If client_view_key is for 'BTC/USDT' '1m' OHLCV, only send
                        #          OHLCV data for 'BTC/USDT' '1m'.

                        if stream_type_from_payload == StreamType.OHLCV and \
                           view_tf_or_type_for_client == data_from_redis.get('timeframe') and \
                           view_symbol_for_client == data_from_redis.get('symbol'):
                            # This message is OHLCV and matches the symbol and timeframe of this client's view.
                            bar = data_from_redis # data_from_redis should be an OHLCVBar-like dict
                            client_message_to_send = {
                                "type": "update",
                                "symbol": view_symbol_for_client, # Echo back what client subscribed to
                                "timeframe": view_tf_or_type_for_client,
                                "payload": {
                                    "ohlc": [[bar['timestamp'], bar['open'], bar['high'], bar['low'], bar['close']]],
                                    "volume": [[bar['timestamp'], bar['volume']]],
                                    "initial_batch": False # This is a live update
                                }
                            }
                        elif stream_type_from_payload == StreamType.TRADES and \
                             view_tf_or_type_for_client == StreamType.TRADES.value and \
                             view_symbol_for_client == data_from_redis.get('symbol'):
                            # This message is for TRADES and matches the symbol of this client's TRADES view.
                            client_message_to_send = {
                                "type": "trade_update",
                                "symbol": view_symbol_for_client,
                                # "timeframe" might be null or irrelevant if client subscribed directly to trades
                                "payload": data_from_redis # Contains the trade data
                            }
                        elif stream_type_from_payload == StreamType.USER_ORDERS and \
                             view_tf_or_type_for_client == StreamType.USER_ORDERS.value:
                            # For USER_ORDERS, the client subscribed to their own orders for a provider.
                            # The symbol in client_view_key might be a placeholder.
                            # StreamingManager would have published this using a user-specific context or channel.
                            # We assume data_from_redis is correctly scoped to this user by StreamingManager.
                            client_message_to_send = {
                                "type": "user_order_update",
                                "provider": data_from_redis.get("provider"), # Pass along provider context
                                "payload": data_from_redis # Contains the order update
                            }
                        # TODO: Add similar conditional blocks for StreamType.ORDER_BOOK
                        # elif stream_type_from_payload == StreamType.ORDER_BOOK and ...

                        if client_message_to_send:
                            if not await self._send_to_websocket(ws, client_message_to_send):
                                logger.warning(f"{log_prefix} Send to WebSocket failed. Client likely disconnected. Stopping listener.")
                                break # Exit loop, task will terminate.
                        # else:
                        #    logger.debug(f"{log_prefix} Message from Redis did not match filter criteria for this client view. Data: {data_from_redis}")

                    except json.JSONDecodeError:
                        logger.error(f"{log_prefix} JSONDecodeError processing message data from Redis: {message.get('data')}", exc_info=True)
                    except KeyError as ke:
                        logger.error(f"{log_prefix} KeyError processing parsed Redis message: {ke}. Payload: {data_from_redis if 'data_from_redis' in locals() else 'N/A'}", exc_info=True)
                    except Exception as e_proc: # Catch-all for other processing errors
                        logger.error(f"{log_prefix} Error processing/sending message from Redis: {e_proc}", exc_info=True)

        except asyncio.CancelledError:
            logger.info(f"{log_prefix} Listener task was explicitly cancelled.")
        except redis_exceptions.ConnectionError as e_rc_outer: # Should be caught by inner loop ideally
            logger.error(f"{log_prefix} Outer Redis connection error: {e_rc_outer}. Listener task stopping.", exc_info=True)
        except Exception as e_outer_loop: # Catch-all for unexpected errors in the listener's main loop
            logger.error(f"{log_prefix} Unexpected error in listener main loop: {e_outer_loop}", exc_info=True)
        finally:
            # Ensure Redis PubSub client is cleaned up.
            if pubsub_client:
                try:
                    if pubsub_client.connection and redis_channel_name: # Check if connection and channel name are valid
                        await pubsub_client.unsubscribe(redis_channel_name)
                        logger.debug(f"{log_prefix} Unsubscribed from Redis channel '{redis_channel_name}'.")
                    await pubsub_client.close() # Close the pubsub connection pool
                    logger.debug(f"{log_prefix} PubSub client closed.")
                except Exception as e_unsub_close:
                    logger.error(f"{log_prefix} Error during Redis PubSub unsubscribe/close for '{redis_channel_name}': {e_unsub_close}", exc_info=True)
            logger.info(f"{log_prefix} Listener task finished.")


    async def _cleanup_specific_client_view(
        self,
        ws: WebSocketClient,
        client_view_key_to_cleanup: SubscriptionKey,
        called_from_disconnect: bool = False # To adjust logging detail slightly
    ):
        """
        Internal helper to clean up resources for a single specific subscription view
        of a WebSocket client.

        This includes:
        - Cancelling its Redis listener task.
        - Removing its entry from internal tracking dictionaries.
        - Unregistering it from SubscriptionRegistry.
        - Instructing StreamingManager to release its hold on the underlying stream.

        Args:
            ws (WebSocketClient): The WebSocket client.
            client_view_key_to_cleanup (SubscriptionKey): The specific view to clean up.
            called_from_disconnect (bool): If true, indicates this is part of a full client disconnect cleanup.
        """
        ws_id_for_log = getattr(ws, 'id', id(ws))
        log_prefix = f"SubSvc CleanupView (WS:{ws_id_for_log}, View:{client_view_key_to_cleanup}):"
        logger.info(f"{log_prefix} Starting cleanup for specific client view.")

        # 1. Retrieve and remove details for this view from internal tracking
        redis_channel_to_stop = self._client_view_to_redis_channel.get(ws, {}).pop(client_view_key_to_cleanup, None)
        manager_key_to_release = self._client_view_to_manager_key.get(ws, {}).pop(client_view_key_to_cleanup, None)
        user_id_for_release_context = self._client_user_order_contexts.get(ws, {}).pop(client_view_key_to_cleanup, None)

        # Clean up empty per-client dicts if this was the last view for that type of mapping
        if ws in self._client_view_to_redis_channel and not self._client_view_to_redis_channel[ws]:
            del self._client_view_to_redis_channel[ws]
        if ws in self._client_view_to_manager_key and not self._client_view_to_manager_key[ws]:
            del self._client_view_to_manager_key[ws]
        if ws in self._client_user_order_contexts and not self._client_user_order_contexts[ws]:
            del self._client_user_order_contexts[ws]


        # 2. Cancel and remove the specific Redis listener task for this channel
        listener_task_to_cancel: Optional[asyncio.Task] = None
        if redis_channel_to_stop and ws in self._client_channel_listeners:
            listener_task_to_cancel = self._client_channel_listeners[ws].pop(redis_channel_to_stop, None)
            if not self._client_channel_listeners[ws]: # If no more listeners for this ws
                del self._client_channel_listeners[ws]

        if listener_task_to_cancel and not listener_task_to_cancel.done():
            logger.debug(f"{log_prefix} Cancelling Redis listener task for channel '{redis_channel_to_stop}'.")
            listener_task_to_cancel.cancel()
            try:
                await listener_task_to_cancel
            except asyncio.CancelledError:
                logger.debug(f"{log_prefix} Listener task for '{redis_channel_to_stop}' successfully cancelled.")
            except Exception as e_await_cancel:
                logger.error(f"{log_prefix} Error awaiting listener task cancellation for '{redis_channel_to_stop}': {e_await_cancel}", exc_info=True)

        # 3. Unregister this specific view from SubscriptionRegistry
        # The registry was updated to handle unregister_specific
        market, provider, symbol, tf_or_type = client_view_key_to_cleanup
        self._registry.unregister_specific(ws, market, provider, symbol, tf_or_type)

        # 4. Instruct StreamingManager to release its hold on the underlying stream
        if manager_key_to_release:
            logger.info(f"{log_prefix} Releasing stream '{manager_key_to_release}' in StreamingManager.")
            sm_market, sm_provider, sm_symbol_norm, sm_stream_type, sm_timeframe, _sm_user_ctx_from_key = manager_key_to_release
            
            # Determine user_id for plugin instance when releasing stream, if it was user-specific.
            # user_id_for_release_context was stored if this view was USER_ORDERS.
            # For other stream types, if they used an authenticated plugin instance via user_id,
            # that user_id would have been passed as user_id_for_plugin to SM.ensure_stream_active.
            # SM.release_stream needs this same user_id_for_plugin if the plugin instance is user-specific.
            uid_for_sm_plugin_release = user_id_for_release_context # This is the original user_id used for this stream

            try:
                await self.streaming_manager.release_stream(
                    market=sm_market, provider=sm_provider, symbol=sm_symbol_norm, # Use normalized symbol from ManagerKey
                    stream_type=sm_stream_type,
                    timeframe=sm_timeframe,
                    user_id_for_plugin=uid_for_sm_plugin_release,
                    user_id_context_for_key=user_id_for_release_context if sm_stream_type == StreamType.USER_ORDERS else None
                )
            except Exception as e_release:
                logger.error(f"{log_prefix} Error releasing stream '{manager_key_to_release}' via StreamingManager: {e_release}", exc_info=True)
        else:
            logger.warning(f"{log_prefix} No ManagerStreamKey found for this view; cannot release from StreamingManager. This might be okay if stream activation failed.")

        if not called_from_disconnect: # Avoid redundant logging if part of a larger disconnect cleanup
            logger.info(f"{log_prefix} Cleanup complete for this view.")


    async def handle_subscribe_request(
        self,
        ws: WebSocketClient,
        market: str,
        provider: str,
        symbol: str,
        requested_stream_type_str: str,
        requested_timeframe: Optional[str] = None,
        since: Optional[int] = None, # For fetching initial historical data
        user_id: Optional[str] = None # User ID from auth (e.g., JWT), for user-specific streams/plugins
    ):
        """
        Handles a subscription request from a WebSocket client for a specific data view.
        Allows multiple distinct views per client.

        Args:
            ws: The WebSocket client connection.
            market: Market identifier (e.g., "crypto").
            provider: Provider identifier (e.g., "binance").
            symbol: Trading symbol (e.g., "BTC/USDT").
            requested_stream_type_str: String representation of the stream type (e.g., "ohlcv", "trades").
            requested_timeframe: Timeframe string (e.g., "1m"), required for "ohlcv" type.
            since: Optional timestamp (ms) to fetch initial historical data from.
            user_id: Optional user ID for authenticated streams or user-specific plugin instances.
        """
        ws_id_for_log = getattr(ws, 'id', id(ws))

        # Normalize inputs for keys
        norm_market = market.lower().strip()
        norm_provider = provider.lower().strip()
        norm_symbol = symbol.upper().strip() # SubscriptionKey uses this, SM normalizes further for StreamKey
        norm_req_tf = requested_timeframe.lower().strip() if requested_timeframe else None

        try:
            stream_type_to_ensure = StreamType(requested_stream_type_str.lower())
        except ValueError:
            logger.warning(f"SubSvc Subscribe (WS:{ws_id_for_log}): Invalid stream_type_str '{requested_stream_type_str}'.")
            await self._send_to_websocket(ws, {"type": "error", "payload": {"message": f"Invalid stream type: {requested_stream_type_str}"}})
            return

        # Client's view key uses the potentially non-SM-normalized symbol for client-facing identification
        client_view_identifier = norm_req_tf if stream_type_to_ensure == StreamType.OHLCV else stream_type_to_ensure.value
        if not client_view_identifier: # Should not happen if stream_type_to_ensure logic is correct
            logger.error(f"SubSvc Subscribe (WS:{ws_id_for_log}): Internal error determining client_view_identifier for {stream_type_to_ensure}.")
            await self._send_to_websocket(ws, {"type": "error", "payload": {"message": "Internal subscription error."}})
            return
        client_view_key: SubscriptionKey = (norm_market, norm_provider, norm_symbol, client_view_identifier)

        log_prefix = f"SubSvc Subscribe (WS:{ws_id_for_log}, View:{client_view_key}, StreamTypeVal:{stream_type_to_ensure.value})"
        logger.info(f"{log_prefix} Request received. User: {user_id}.")

        # --- Ensure client's internal dictionaries are initialized ---
        self._client_channel_listeners.setdefault(ws, {})
        self._client_view_to_redis_channel.setdefault(ws, {})
        self._client_view_to_manager_key.setdefault(ws, {})
        self._client_user_order_contexts.setdefault(ws, {})

        # --- Check if already subscribed to this exact view ---
        if client_view_key in self._client_view_to_redis_channel.get(ws, {}):
            logger.info(f"{log_prefix} Client already subscribed to this exact view. Re-confirming or re-sending history.")
            # Optionally, resend initial data if behavior is to "refresh" on re-subscribe
            # For now, just acknowledge. If they want to "force refresh", they might need to unsub/sub.
            await self._send_to_websocket(ws, {"type": "status", "payload": {"message": f"Already subscribed to {client_view_key}. Live updates active."}})
            # Consider re-sending initial data here if that's desired on re-subscribe to same view.
            # For now, we assume the existing listener is fine.
            return

        # --- User ID context for StreamingManager's StreamKey (for USER_ORDERS type) ---
        user_id_for_sm_key_context = user_id if stream_type_to_ensure == StreamType.USER_ORDERS else None
        if stream_type_to_ensure == StreamType.USER_ORDERS and not user_id:
            logger.error(f"{log_prefix} USER_ORDERS stream requires an authenticated user_id, but none was provided.")
            await self._send_to_websocket(ws, {"type": "error", "payload": {"message": "Authentication required for user order stream."}})
            return

        # --- Generate StreamingManager's key and the Redis channel name ---
        # Note: StreamingManager's _generate_stream_key uses a more normalized symbol for its internal key.
        manager_stream_key = self.streaming_manager._generate_stream_key(
            norm_market, norm_provider, norm_symbol, # Pass user-facing symbol, SM will normalize it
            stream_type_to_ensure,
            timeframe=norm_req_tf if stream_type_to_ensure == StreamType.OHLCV else None,
            user_id_context=user_id_for_sm_key_context
        )
        redis_channel_name = self.streaming_manager._get_redis_channel_name(manager_stream_key)

        # 1. Register this new view with SubscriptionRegistry
        self._registry.register(ws, norm_market, norm_provider, norm_symbol, client_view_identifier)

        # 2. Send initial historical data (if applicable, e.g., for OHLCV charts)
        initial_data_sent_successfully = True
        if stream_type_to_ensure == StreamType.OHLCV and norm_req_tf:
            try:
                if not await self._send_to_websocket(ws, {"type": "status", "payload": {"message": f"Subscribed to {client_view_key}. Fetching history..."}}):
                    initial_data_sent_successfully = False # Stop if we can't even send status

                if initial_data_sent_successfully:
                    initial_bars_list = await self.market_service.fetch_ohlcv(
                        market=norm_market, provider=norm_provider, symbol=norm_symbol, timeframe=norm_req_tf,
                        since=since, limit=int(current_app.config.get("INITIAL_CHART_POINTS", 200)),
                        user_id=user_id # Pass user_id for MarketService if plugin needs auth
                    )
                    logger.info(f"{log_prefix} Initial history fetched: {len(initial_bars_list)} bars for {norm_req_tf}.")
                    ohlc_data = [[b['timestamp'], b['open'], b['high'], b['low'], b['close']] for b in initial_bars_list]
                    volume_data = [[b['timestamp'], b['volume']] for b in initial_bars_list]
                    initial_payload = {"ohlc": ohlc_data, "volume": volume_data, "initial_batch": True}

                    if not await self._send_to_websocket(ws, {"type": "data", "payload": initial_payload, "symbol": norm_symbol, "timeframe": norm_req_tf}):
                        initial_data_sent_successfully = False
            except Exception as e_hist:
                logger.error(f"{log_prefix} Error fetching/sending initial OHLCV history: {e_hist}", exc_info=True)
                await self._send_to_websocket(ws, {"type": "error", "payload": {"message": f"Error loading initial chart data for {client_view_key}: {str(e_hist)[:100]}"}})
                initial_data_sent_successfully = False

            if not initial_data_sent_successfully:
                logger.warning(f"{log_prefix} Failed to send initial status/data. Cleaning up this subscription attempt.")
                # Clean up the registration and do not proceed to activate stream or listener
                await self._cleanup_specific_client_view(ws, client_view_key) # This calls registry.unregister_specific
                return
        else: # For other stream types, just send a basic subscribed status
            if not await self._send_to_websocket(ws, {"type": "status", "payload": {"message": f"Subscribed to {client_view_key}."}}):
                # If status send fails, client is likely gone. Clean up registration.
                await self._cleanup_specific_client_view(ws, client_view_key)
                return

        # 3. Instruct StreamingManager to ensure the underlying data stream is active.
        #    Pass user_id for plugin instance auth, and user_id_for_sm_key_context for StreamKey generation.
        logger.info(f"{log_prefix} Ensuring underlying stream '{manager_stream_key}' (Redis: '{redis_channel_name}') is active.")
        stream_activated = await self.streaming_manager.ensure_stream_active(
            market=norm_market, provider=norm_provider, symbol=norm_symbol, # Pass user-facing symbol
            stream_type=stream_type_to_ensure,
            timeframe=norm_req_tf if stream_type_to_ensure == StreamType.OHLCV else None,
            user_id_for_plugin=user_id,                 # For getting authenticated plugin instance
            user_id_context_for_key=user_id_for_sm_key_context # For StreamKey's own uniqueness if user-specific stream
        )

        if not stream_activated:
            err_msg = f"Failed to activate underlying data stream ({stream_type_to_ensure.value}) via StreamingManager for {manager_stream_key}."
            logger.error(f"{log_prefix} {err_msg}")
            await self._send_to_websocket(ws, {"type": "error", "payload": {"message": f"Could not connect to live data feed for {client_view_key}."}})
            # Clean up registration as stream activation failed. StreamingManager handles its own ref count decrement on failure.
            await self._cleanup_specific_client_view(ws, client_view_key, call_release_stream=False) # SM failed, so no SM release needed by us
            return

        logger.info(f"{log_prefix} Underlying stream '{manager_stream_key}' is now active, publishing to Redis '{redis_channel_name}'.")

        # 4. Store mappings and start the dedicated Redis listener task for this client view.
        self._client_view_to_redis_channel[ws][client_view_key] = redis_channel_name
        self._client_view_to_manager_key[ws][client_view_key] = manager_stream_key
        if stream_type_to_ensure == StreamType.USER_ORDERS and user_id: # Store user_id for user_orders release
             self._client_user_order_contexts[ws][client_view_key] = user_id

        listener_task_name = f"ClientListener_{ws_id_for_log}_{client_view_key}"
        new_listener_task = asyncio.create_task(
            self._redis_listener_for_client_channel(ws, client_view_key, redis_channel_name),
            name=listener_task_name
        )
        # Store this new task, associated with its specific Redis channel for this client
        self._client_channel_listeners[ws][redis_channel_name] = new_listener_task

        logger.info(f"{log_prefix} Started Redis listener task '{listener_task_name}' for channel '{redis_channel_name}'.")
        await self._send_to_websocket(ws, {"type": "status", "payload": {"message": f"Live updates for {client_view_key} enabled."}})


    async def handle_client_unsubscribe_message(
        self,
        ws: WebSocketClient,
        market: str,
        provider: str,
        symbol: str,
        requested_stream_type_str: str,
        requested_timeframe: Optional[str] = None
    ):
        """
        Handles an explicit unsubscribe message from the client for a specific data view.
        The client must specify which view it wants to unsubscribe from.

        Args:
            ws: The WebSocket client connection.
            market: Market of the view to unsubscribe from.
            provider: Provider of the view to unsubscribe from.
            symbol: Symbol of the view to unsubscribe from.
            requested_stream_type_str: Stream type string (e.g., "ohlcv", "trades").
            requested_timeframe: Timeframe (if "ohlcv") of the view to unsubscribe from.
        """
        ws_id_for_log = getattr(ws, 'id', id(ws))
        try:
            # Normalize inputs to form the key consistently
            norm_market = market.lower().strip()
            norm_provider = provider.lower().strip()
            norm_symbol = symbol.upper().strip()
            norm_req_tf = requested_timeframe.lower().strip() if requested_timeframe else None
            
            stream_type_val = StreamType(requested_stream_type_str.lower())
            view_identifier = norm_req_tf if stream_type_val == StreamType.OHLCV else stream_type_val.value
            client_view_key_to_unsub: SubscriptionKey = (norm_market, norm_provider, norm_symbol, view_identifier)

            logger.info(f"SubSvc UnsubscribeMsg (WS:{ws_id_for_log}): Received request to unsubscribe from view {client_view_key_to_unsub}")

            if ws in self._client_view_to_redis_channel and \
               client_view_key_to_unsub in self._client_view_to_redis_channel[ws]:
                await self._cleanup_specific_client_view(ws, client_view_key_to_unsub)
                await self._send_to_websocket(ws, {"type": "status", "payload": {"message": f"Successfully unsubscribed from {client_view_key_to_unsub}."}})
            else:
                logger.warning(f"SubSvc UnsubscribeMsg (WS:{ws_id_for_log}): Client tried to unsubscribe from view {client_view_key_to_unsub}, but was not actively subscribed to it.")
                await self._send_to_websocket(ws, {"type": "error", "payload": {"message": f"Not currently subscribed to {client_view_key_to_unsub}."}})
        except ValueError: # From StreamType(requested_stream_type_str.lower())
            logger.warning(f"SubSvc UnsubscribeMsg (WS:{ws_id_for_log}): Invalid stream_type '{requested_stream_type_str}' in unsubscribe message.")
            await self._send_to_websocket(ws, {"type": "error", "payload": {"message": f"Invalid stream type for unsubscribe: {requested_stream_type_str}"}})
        except Exception as e_unsub_msg: # Catch-all for unexpected errors
            logger.error(f"SubSvc UnsubscribeMsg (WS:{ws_id_for_log}): Error processing unsubscribe message: {e_unsub_msg}", exc_info=True)
            await self._send_to_websocket(ws, {"type": "error", "payload": {"message": "Error processing unsubscribe request."}})


    async def handle_client_disconnect(self, ws: WebSocketClient):
        """
        Cleans up all active subscriptions and resources for a disconnected
        WebSocket client.

        Args:
            ws (WebSocketClient): The WebSocket client connection that has disconnected.
        """
        ws_id_for_log = getattr(ws, 'id', id(ws))
        logger.info(f"SubscriptionService: Client {ws_id_for_log} disconnected. Cleaning up all its subscriptions.")

        # Get all active subscription keys for this specific WebSocket client
        # Use the updated SubscriptionRegistry method
        active_views_for_client = self._registry.get_keys_for_ws(ws)

        if not active_views_for_client:
            logger.info(f"SubscriptionService: Client {ws_id_for_log} had no active subscriptions in registry upon disconnect.")
            # Still, ensure any lingering internal state for this ws is cleared.
            self._client_channel_listeners.pop(ws, None)
            self._client_view_to_redis_channel.pop(ws, None)
            self._client_view_to_manager_key.pop(ws, None)
            self._client_user_order_contexts.pop(ws, None)
            return

        logger.info(f"SubscriptionService: Client {ws_id_for_log} has {len(active_views_for_client)} active views to clean up: {active_views_for_client}")
        for view_key in list(active_views_for_client): # Iterate over a copy if cleanup modifies the source
            logger.debug(f"SubscriptionService: Cleaning up view {view_key} for disconnected client {ws_id_for_log}.")
            # _cleanup_specific_client_view will handle task cancellation, SM release, and registry unregistration.
            await self._cleanup_specific_client_view(ws, view_key, called_from_disconnect=True)

        # Final sanity clear for this client's entries in case any were missed or partially cleaned.
        # _cleanup_specific_client_view should handle removal from these dicts, but this is a safeguard.
        self._client_channel_listeners.pop(ws, None)
        self._client_view_to_redis_channel.pop(ws, None)
        self._client_view_to_manager_key.pop(ws, None)
        self._client_user_order_contexts.pop(ws, None)
        # _registry.unregister_all_for_ws(ws) would also be effective if _cleanup_specific_client_view didn't call registry.unregister_specific
        # Since it does, this explicit call to unregister_all_for_ws might be redundant but harmless.
        # Let's rely on _cleanup_specific_client_view to have handled individual registry entries.

        logger.info(f"SubscriptionService: Cleanup complete for all views of disconnected client {ws_id_for_log}.")


    async def shutdown(self) -> None:
        """
        Gracefully stops all active client Redis listener tasks and cleans up all subscriptions.
        Called during application shutdown.
        """
        logger.info(f"SubscriptionService: Shutting down... Processing all connected WebSocket clients.")

        # Get a list of all currently connected WebSocket clients that have entries in our tracking dicts.
        # Using _client_channel_listeners as the primary source of 'active' clients.
        all_connected_clients = list(self._client_channel_listeners.keys())

        for ws_client in all_connected_clients:
            ws_id_for_log = getattr(ws_client, 'id', id(ws_client))
            logger.info(f"SubscriptionService: Processing shutdown for client {ws_id_for_log}.")
            # This will iterate through all of this client's views and clean them up.
            await self.handle_client_disconnect(ws_client)

        # Sanity clear of all tracking dictionaries, though handle_client_disconnect should have emptied them.
        self._client_channel_listeners.clear()
        self._client_view_to_redis_channel.clear()
        self._client_view_to_manager_key.clear()
        self._client_user_order_contexts.clear()
        self._registry.clear_all() # Clears the SubscriptionRegistry fully.

        logger.info("SubscriptionService: Shutdown complete. All client listeners processed and registries cleared.")