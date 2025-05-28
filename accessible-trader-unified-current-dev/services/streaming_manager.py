# services/streaming_manager.py

import asyncio
import logging
import json
import hashlib # For change detection in polling
from typing import Dict, List, Set, Tuple, Optional, Callable, Awaitable, Any
from enum import Enum
from redis.asyncio import Redis as AsyncRedis

from services.market_service import MarketService
from plugins.base import MarketPlugin, PluginError, PluginFeatureNotSupportedError, OHLCVBar, Order, Ticker, OrderBook # Import relevant data types

logger = logging.getLogger(__name__) # Or "StreamingManager"

class StreamType(Enum):
    """Defines the types of real-time data streams supported."""
    TRADES = "trades"
    OHLCV = "ohlcv"
    ORDER_BOOK = "order_book"
    USER_ORDERS = "user_orders"

StreamKey = Tuple[str, str, str, StreamType, Optional[str], Optional[str]]

DEFAULT_POLLING_INTERVAL_SEC = 10.0 # A generic default if specific type interval not found

class StreamingManager:
    """
    Manages subscriptions to real-time data feeds from MarketPlugins.
    It attempts to use native streaming (e.g., WebSockets) from plugins first.
    If native streaming is not supported for a requested data type, it can
    fall back to periodically polling the plugin's REST API endpoints.
    All successfully acquired data (streamed or polled) is published to
    standardized Redis Pub/Sub channels for consumption by other services
    like SubscriptionService.
    """

    def __init__(self, market_service: MarketService, redis_client: AsyncRedis, app_config: Dict[str, Any]): # Added app_config
        """
        Initializes the StreamingManager.

        Args:
            market_service: The application's MarketService instance.
            redis_client: The raw asynchronous Redis client for Pub/Sub.
            app_config: The application's configuration object (e.g., current_app.config).
        """
        if not isinstance(market_service, MarketService): #
            raise TypeError("StreamingManager requires a valid MarketService instance.") #
        # Basic check for redis_client, actual type is redis.asyncio.client.Redis
        if not hasattr(redis_client, 'publish') or not hasattr(redis_client, 'pubsub'):
            raise TypeError("StreamingManager requires a valid redis.asyncio.Redis compatible client instance.")


        self._market_service: MarketService = market_service #
        self._redis_client: AsyncRedis = redis_client #
        self._app_config: Dict[str, Any] = app_config # Store app_config for polling intervals

        # For native streams: Key -> True (placeholder, plugin manages its own task)
        self._active_native_stream_placeholders: Dict[StreamKey, bool] = {}
        
        # For polled streams: Key -> asyncio.Task (task managed by StreamingManager)
        self._active_polling_tasks: Dict[StreamKey, asyncio.Task] = {}
        
        self._stream_reference_counts: Dict[StreamKey, int] = {}
        self._management_lock = asyncio.Lock()
        
        logger.info("StreamingManager initialized (with polling fallback capability).") #

    def _generate_stream_key(
        self, 
        market: str, 
        provider: str, 
        symbol: str, 
        stream_type: StreamType, 
        timeframe: Optional[str] = None,
        user_id_context: Optional[str] = None
    ) -> StreamKey:
        """Generates a unique, normalized key for managing a data stream (native or polled)."""
        market_norm = market.lower().strip() #
        provider_norm = provider.lower().strip() #
        symbol_norm = symbol.upper().replace("/", "_").replace("-", "_").strip() #
        tf_norm = timeframe.lower().strip() if timeframe else None #
        user_ctx_norm = str(user_id_context).strip() if user_id_context else None #

        if stream_type == StreamType.USER_ORDERS:
            if not user_ctx_norm: #
                raise ValueError("user_id_context is required for USER_ORDERS stream type.") #
            return (market_norm, provider_norm, f"user_{user_ctx_norm}", stream_type, None, user_ctx_norm) #
        
        return (market_norm, provider_norm, symbol_norm, stream_type, tf_norm, user_ctx_norm) #

    def _get_redis_channel_name(self, stream_key: StreamKey) -> str:
        """Generates a Redis Pub/Sub channel name from a StreamKey."""
        market, provider, main_id, stream_type_enum, secondary_id, _ = stream_key #
        parts = ["stream", stream_type_enum.value, provider, main_id] #
        if secondary_id: # e.g., timeframe for OHLCV
            parts.append(secondary_id) #
        return ":".join(parts) #

    async def _handle_plugin_message(self, message_data: Dict[str, Any], stream_key_for_context: StreamKey):
        """
        Internal callback for native plugin streams OR formatter for polled data.
        Receives data, enriches with context, serializes to JSON, and publishes to Redis.
        """
        try:
            ctx_market, ctx_provider, ctx_symbol_norm, ctx_stream_type, ctx_timeframe, _ = stream_key_for_context #

            # Ensure essential context is in the message_data before publishing
            message_data.setdefault('provider', ctx_provider) #
            message_data.setdefault('symbol', ctx_symbol_norm.replace("_", "/")) # Denormalize symbol for payload #
            message_data.setdefault('stream_type', ctx_stream_type.value) #
            if ctx_timeframe and 'timeframe' not in message_data : # Only add if not already present (e.g. from polled OHLCV)
                message_data.setdefault('timeframe', ctx_timeframe) #
            
            if not all(k in message_data for k in ['provider', 'symbol', 'stream_type']): #
                logger.warning(f"StreamingManager ({stream_key_for_context}): Message missing essential fields after enrichment: {message_data}. Discarding.") #
                return

            redis_channel = self._get_redis_channel_name(stream_key_for_context) #
            # Ensure datetime objects or other non-JSON serializable types are handled
            # Plugins should ideally do this, or it can be done here with json.dumps(default=str)
            message_payload_str = json.dumps(message_data, default=str) #
            
            await self._redis_client.publish(redis_channel, message_payload_str) #
            logger.debug(f"StreamingManager ({stream_key_for_context}): Published to Redis '{redis_channel}': {message_payload_str[:200]}...") #

        except json.JSONEncodeError as e_json: #
            logger.error(f"StreamingManager ({stream_key_for_context}): Failed to serialize message to JSON: {message_data}. Error: {e_json}", exc_info=True) #
        except AttributeError as e_attr: 
            logger.error(f"StreamingManager ({stream_key_for_context}): Malformed message_data: {message_data}. Error: {e_attr}", exc_info=True) #
        except Exception as e: 
            logger.error(f"StreamingManager ({stream_key_for_context}): Error in _handle_plugin_message: {e}", exc_info=True) #

    def _get_polling_config(self, plugin: MarketPlugin, stream_key: StreamKey, features: Dict[str, bool]) -> Optional[Dict[str, Any]]:
        """
        Determines the REST method and parameters for polling based on stream_type and plugin features.
        Returns a dict with "method_name", "interval_config_key", "initial_params" or None.
        """
        _market, _provider, _symbol_norm, stream_type, timeframe, _user_ctx = stream_key
        
        config = None
        if stream_type == StreamType.ORDER_BOOK and features.get("fetch_order_book"):
            config = {"method_name": "fetch_order_book", 
                        "interval_config_key": "POLLING_INTERVAL_ORDER_BOOK_SEC", 
                        "initial_params": {"limit": 20}} # Example default limit
        elif stream_type == StreamType.TRADES and features.get("fetch_ticker"): # Using ticker for "latest trade" idea
            config = {"method_name": "fetch_ticker", 
                        "interval_config_key": "POLLING_INTERVAL_TRADES_SEC", 
                        "initial_params": {}}
        elif stream_type == StreamType.OHLCV and features.get("fetch_latest_ohlcv") and timeframe:
            config = {"method_name": "fetch_latest_ohlcv", 
                        "interval_config_key": "POLLING_INTERVAL_OHLCV_SEC", 
                        "initial_params": {"timeframe": timeframe}} # Pass timeframe to method
        elif stream_type == StreamType.USER_ORDERS and features.get("fetch_open_orders"):
            # Polling open orders is a snapshot, not ideal for emulating event stream but can show changes.
            config = {"method_name": "fetch_open_orders", 
                        "interval_config_key": "POLLING_INTERVAL_USER_ORDERS_SEC", 
                        "initial_params": {}}
        
        if config:
            logger.info(f"Polling fallback for {stream_key}: Configured for plugin method '{config['method_name']}'.")
        else:
            logger.info(f"Polling fallback for {stream_key}: No suitable REST method found in plugin features.")
        return config

    async def _polling_loop_for_key(
            self, 
            plugin: MarketPlugin, 
            stream_key: StreamKey, 
            plugin_method_name: str, 
            poll_interval_sec: float, 
            method_initial_params: Dict[str, Any]
        ):
        """The actual polling loop task for a given stream key."""
        log_prefix = f"PollingLoop ({stream_key})"
        logger.info(f"{log_prefix} Starting with method '{plugin_method_name}' every {poll_interval_sec}s.")
        
        last_data_hash = None
        _market, _provider, symbol_norm, stream_type, timeframe, _user_ctx = stream_key
        denormalized_symbol = symbol_norm.replace("_", "/") # For plugin calls if needed

        while True: # Loop indefinitely until cancelled
            if not (stream_key in self._active_polling_tasks and not self._active_polling_tasks[stream_key].done()):
                 logger.info(f"{log_prefix} Task no longer active or in dictionary. Terminating.")
                 break
            try:
                await asyncio.sleep(poll_interval_sec)

                # Call the designated plugin REST method
                fetch_method = getattr(plugin, plugin_method_name)
                current_data: Any # Type will vary based on method (Ticker, OrderBook, OHLCVBar, List[Order])
                
                # Construct arguments for the plugin method call dynamically
                call_args = {"symbol": denormalized_symbol}
                if "timeframe" in method_initial_params and method_initial_params["timeframe"]: # For fetch_latest_ohlcv
                    call_args["timeframe"] = method_initial_params["timeframe"]
                if "limit" in method_initial_params and plugin_method_name == "fetch_order_book": # For fetch_order_book
                    call_args["limit"] = method_initial_params["limit"]
                # For fetch_open_orders, symbol might be optional in the method, or passed via method_initial_params
                # If method_initial_params needs to override symbol (e.g. for None symbol in fetch_open_orders):
                # call_args.update(method_initial_params) # More general way if params dict aligns
                
                current_data = await fetch_method(**call_args)

                if current_data is None and stream_type != StreamType.OHLCV: # fetch_latest_ohlcv can return None legitimately
                    logger.debug(f"{log_prefix} Poll returned None data from {plugin_method_name}.")
                    # Optional: consider if None should clear last_data_hash or be treated as no change
                    continue

                # --- Change Detection (simple hash-based) ---
                # For lists (like fetch_open_orders), this hashes the list representation.
                # More sophisticated diffing might be needed for user_orders to emit individual changes.
                current_data_str = json.dumps(current_data, sort_keys=True, default=str)
                current_hash = hashlib.md5(current_data_str.encode('utf-8')).hexdigest()

                if current_hash != last_data_hash:
                    last_data_hash = current_hash
                    logger.debug(f"{log_prefix} Data changed for {plugin_method_name}. New hash: {current_hash}")
                    
                    # --- Prepare data for _handle_plugin_message ---
                    # _handle_plugin_message expects a dictionary that is essentially the payload
                    # It will add provider, symbol, stream_type context from stream_key if not present.
                    # Most plugin fetch methods should return data that can be directly used or easily adapted.
                    payload_for_redis: Dict[str, Any]
                    if isinstance(current_data, dict):
                        payload_for_redis = current_data
                    elif isinstance(current_data, list): # e.g. for fetch_open_orders
                        # Wrap list in a standard way if _handle_plugin_message doesn't handle lists directly
                        payload_for_redis = {"items": current_data, "type": "snapshot"} # Example wrapper
                    elif current_data is None and stream_type == StreamType.OHLCV: # Handle None for fetch_latest_ohlcv
                        # Decide if None should be published or skipped. Skipping for now.
                        logger.debug(f"{log_prefix} fetch_latest_ohlcv returned None, skipping publish.")
                        continue
                    else:
                        payload_for_redis = {"value": current_data} # Generic wrapper for other types

                    await self._handle_plugin_message(payload_for_redis, stream_key)
                else:
                    logger.debug(f"{log_prefix} No data change detected for {plugin_method_name}.")
            
            except asyncio.CancelledError:
                logger.info(f"{log_prefix} Polling task cancelled.")
                break
            except PluginFeatureNotSupportedError: # Should ideally be caught before starting polling
                logger.error(f"{log_prefix} Plugin does not support {plugin_method_name}. Stopping poll.", exc_info=True)
                break
            except PluginError as e_plugin:
                logger.warning(f"{log_prefix} Plugin error during poll ({plugin_method_name}): {e_plugin}. Retrying after delay.")
                await asyncio.sleep(poll_interval_sec * 2) # Longer delay on plugin error
            except Exception as e:
                logger.error(f"{log_prefix} Unexpected error in polling loop: {e}", exc_info=True)
                await asyncio.sleep(poll_interval_sec * 5) # Longest delay for unknown errors before retry
        
        # Final cleanup for this task if it exits the loop
        async with self._management_lock:
            if stream_key in self._active_polling_tasks and self._active_polling_tasks.get(stream_key) == asyncio.current_task():
                self._active_polling_tasks.pop(stream_key, None)
                logger.info(f"{log_prefix} Polling task removed from active tracking.")


    async def ensure_stream_active(
        self, 
        market: str, 
        provider: str, 
        symbol: str,
        stream_type: StreamType, 
        timeframe: Optional[str] = None,
        user_id_for_plugin: Optional[str] = None,
        user_id_context_for_key: Optional[str] = None
    ) -> bool:
        """
        Ensures the data stream is active, using native plugin streaming if available,
        otherwise falling back to REST polling if possible. Manages reference counts.
        """
        if stream_type == StreamType.OHLCV and not timeframe: #
            logger.error(f"StreamingManager: Timeframe is required for OHLCV stream (Market: {market}, Provider: {provider}, Symbol: {symbol}).") #
            return False #
        if stream_type == StreamType.USER_ORDERS and not user_id_context_for_key: #
            logger.error(f"StreamingManager: user_id_context_for_key is required for USER_ORDERS stream (Market: {market}, Provider: {provider}).") #
            return False #
        if stream_type == StreamType.USER_ORDERS and not user_id_for_plugin: #
            logger.warning(f"StreamingManager: user_id_for_plugin not provided for USER_ORDERS stream for {market}/{provider}. Plugin auth may fail.") #

        stream_key = self._generate_stream_key(market, provider, symbol, stream_type, timeframe, user_id_context_for_key) #
        log_prefix = f"EnsureStream ({stream_key})" #

        async with self._management_lock:
            self._stream_reference_counts[stream_key] = self._stream_reference_counts.get(stream_key, 0) + 1 #
            logger.debug(f"{log_prefix}: Reference count incremented to {self._stream_reference_counts[stream_key]}.") #

            if stream_key in self._active_native_stream_placeholders or stream_key in self._active_polling_tasks: #
                logger.debug(f"{log_prefix}: Stream (native or polled) already considered active.") #
                return True

            logger.info(f"{log_prefix}: Stream not active. Attempting to start (native first, then polling fallback).") #
            try:
                plugin: Optional[MarketPlugin] = await self._market_service.get_plugin_instance( #
                    market=market, provider=provider, user_id=user_id_for_plugin #
                )
                if not plugin: #
                    logger.error(f"{log_prefix}: Could not get plugin instance for {market}/{provider} (User: {user_id_for_plugin}).") #
                    self._decrement_ref_count_and_cleanup(stream_key) # Helper to reduce ref count
                    return False

                features = await plugin.get_supported_features() #
                
                # --- Attempt Native Streaming ---
                native_stream_started = False
                if stream_type == StreamType.TRADES and features.get("stream_trades"):
                    await plugin.stream_trades(symbols=[symbol], on_message_callback=lambda msg: self._handle_plugin_message(msg, stream_key))
                    native_stream_started = True
                elif stream_type == StreamType.OHLCV and features.get("stream_ohlcv") and timeframe:
                    await plugin.stream_ohlcv(symbols=[symbol], timeframe=timeframe, on_message_callback=lambda msg: self._handle_plugin_message(msg, stream_key))
                    native_stream_started = True
                elif stream_type == StreamType.ORDER_BOOK and features.get("stream_order_book"):
                    await plugin.stream_order_book(symbols=[symbol], on_message_callback=lambda msg: self._handle_plugin_message(msg, stream_key))
                    native_stream_started = True
                elif stream_type == StreamType.USER_ORDERS and features.get("stream_user_order_updates"):
                    await plugin.stream_user_order_updates(on_message_callback=lambda msg: self._handle_plugin_message(msg, stream_key))
                    native_stream_started = True
                
                if native_stream_started:
                    self._active_native_stream_placeholders[stream_key] = True #
                    logger.info(f"{log_prefix}: Native plugin stream initiated successfully.") #
                    return True

                logger.info(f"{log_prefix}: Native streaming not supported or failed. Attempting polling fallback.")
                # --- Attempt Polling Fallback ---
                polling_config = self._get_polling_config(plugin, stream_key, features)
                if polling_config:
                    poll_interval = float(self._app_config.get(polling_config["interval_config_key"], DEFAULT_POLLING_INTERVAL_SEC))
                    
                    polling_task = asyncio.create_task(
                        self._polling_loop_for_key(
                            plugin, stream_key, 
                            polling_config["method_name"], 
                            poll_interval, 
                            polling_config["initial_params"]
                        ),
                        name=f"PollingTask_{stream_key}"
                    )
                    self._active_polling_tasks[stream_key] = polling_task #
                    logger.info(f"{log_prefix}: Polling fallback task created and started for method '{polling_config['method_name']}'.") #
                    return True

                logger.warning(f"{log_prefix}: No native stream and no suitable polling fallback found for this request.")
                self._decrement_ref_count_and_cleanup(stream_key) #
                return False

            except PluginFeatureNotSupportedError as e_feat: # Should be caught by feature check, but safeguard
                logger.warning(f"{log_prefix}: Feature explicitly not supported by plugin: {e_feat}") #
            except PluginError as e_plugin: # Catch specific PluginErrors
                logger.error(f"{log_prefix}: PluginError while trying to start stream/poll: {e_plugin}", exc_info=True) #
            except Exception as e_start: # Catch any other unexpected errors
                logger.error(f"{log_prefix}: Unexpected error trying to start stream/poll: {e_start}", exc_info=True) #
            
            # If any exception occurred during activation attempt and we didn't return True
            self._decrement_ref_count_and_cleanup(stream_key) #
            return False

    def _decrement_ref_count_and_cleanup(self, stream_key: StreamKey):
        """Helper to decrement reference count and clean up if it reaches zero."""
        if stream_key in self._stream_reference_counts:
            self._stream_reference_counts[stream_key] -=1
            if self._stream_reference_counts[stream_key] <= 0:
                self._stream_reference_counts.pop(stream_key, None)
                # Also ensure it's removed from active tracking if it was added before an error
                self._active_native_stream_placeholders.pop(stream_key, None)
                task = self._active_polling_tasks.pop(stream_key, None)
                if task and not task.done():
                    task.cancel() # Should be handled in release_stream

    async def release_stream(
        self, 
        market: str, 
        provider: str, 
        symbol: str, 
        stream_type: StreamType, 
        timeframe: Optional[str] = None,
        user_id_for_plugin: Optional[str] = None, 
        user_id_context_for_key: Optional[str] = None
    ):
        """
        Decrements reference count. If zero, stops the native plugin stream or the polling task.
        """
        stream_key = self._generate_stream_key(market, provider, symbol, stream_type, timeframe, user_id_context_for_key) #
        log_prefix = f"ReleaseStream ({stream_key})" #

        async with self._management_lock:
            if stream_key not in self._stream_reference_counts: #
                logger.warning(f"{log_prefix}: Stream not found in reference counts. Cannot release.") #
                return

            self._stream_reference_counts[stream_key] -= 1 #
            logger.debug(f"{log_prefix}: Reference count decremented to {self._stream_reference_counts[stream_key]}.") #

            if self._stream_reference_counts[stream_key] <= 0:
                logger.info(f"{log_prefix}: Reference count is zero. Stopping data feed.") #
                self._stream_reference_counts.pop(stream_key, None) #

                # Stop native stream if active
                if self._active_native_stream_placeholders.pop(stream_key, None): #
                    try:
                        plugin: Optional[MarketPlugin] = await self._market_service.get_plugin_instance( #
                            market=market, provider=provider, user_id=user_id_for_plugin #
                        )
                        if plugin: #
                            if stream_type == StreamType.TRADES: #
                                await plugin.stop_trades_stream(symbols=[symbol]) #
                            elif stream_type == StreamType.OHLCV and timeframe: #
                                await plugin.stop_ohlcv_stream(symbols=[symbol], timeframe=timeframe) #
                            elif stream_type == StreamType.ORDER_BOOK: #
                                await plugin.stop_order_book_stream(symbols=[symbol]) #
                            elif stream_type == StreamType.USER_ORDERS: #
                                await plugin.stop_user_order_updates_stream() #
                            logger.info(f"{log_prefix}: Native plugin stream stop method called.") #
                        else: #
                            logger.error(f"{log_prefix}: Could not get plugin instance to stop native stream.") #
                    except Exception as e_stop_native: #
                        logger.error(f"{log_prefix}: Error stopping native plugin stream: {e_stop_native}", exc_info=True) #
                
                # Stop polling task if active
                polling_task = self._active_polling_tasks.pop(stream_key, None) #
                if polling_task and not polling_task.done(): #
                    polling_task.cancel() #
                    logger.info(f"{log_prefix}: Polling task cancelled.") #
                    try:
                        await polling_task # Allow task to process cancellation
                    except asyncio.CancelledError:
                        pass # Expected
                    except Exception as e_await_poll_cancel:
                        logger.error(f"{log_prefix}: Error awaiting cancelled polling task: {e_await_poll_cancel}")
            else:
                logger.debug(f"{log_prefix}: Stream still has {self._stream_reference_counts[stream_key]} references. Not stopping.") #

    async def shutdown(self):
        """
        Stops all active native plugin streams and cancels all polling tasks.
        """
        logger.info(f"StreamingManager: Shutting down... Processing native streams and polling tasks.") #
        
        native_stream_keys_to_stop: List[StreamKey] = []
        polling_tasks_to_cancel: List[asyncio.Task] = []

        async with self._management_lock: #
            native_stream_keys_to_stop = list(self._active_native_stream_placeholders.keys()) #
            self._active_native_stream_placeholders.clear() #

            polling_tasks_to_cancel = list(self._active_polling_tasks.values()) #
            self._active_polling_tasks.clear() #

            self._stream_reference_counts.clear() # Clear all ref counts #

        # Stop native streams
        if native_stream_keys_to_stop:
            logger.info(f"StreamingManager: Stopping {len(native_stream_keys_to_stop)} native plugin streams due to shutdown...")
            for stream_key in native_stream_keys_to_stop:
                market, provider, symbol_norm, stream_type, timeframe, user_id_ctx_key = stream_key #
                denormalized_symbol = symbol_norm.replace("_", "/")
                uid_for_plugin_shutdown = user_id_ctx_key if stream_type == StreamType.USER_ORDERS else None #
                try:
                    plugin: Optional[MarketPlugin] = await self._market_service.get_plugin_instance( #
                        market=market, provider=provider, user_id=uid_for_plugin_shutdown #
                    )
                    if plugin: #
                        if stream_type == StreamType.TRADES: await plugin.stop_trades_stream(symbols=[denormalized_symbol]) #
                        elif stream_type == StreamType.OHLCV and timeframe: await plugin.stop_ohlcv_stream(symbols=[denormalized_symbol], timeframe=timeframe) #
                        elif stream_type == StreamType.ORDER_BOOK: await plugin.stop_order_book_stream(symbols=[denormalized_symbol]) #
                        elif stream_type == StreamType.USER_ORDERS: await plugin.stop_user_order_updates_stream() #
                        logger.debug(f"StreamingManager Shutdown: Stop called for native stream {stream_key}")
                except Exception as e_stop_native:
                    logger.error(f"StreamingManager Shutdown: Error stopping native stream {stream_key}: {e_stop_native}", exc_info=True)

        # Cancel polling tasks
        if polling_tasks_to_cancel:
            logger.info(f"StreamingManager: Cancelling {len(polling_tasks_to_cancel)} polling tasks due to shutdown...")
            for task in polling_tasks_to_cancel:
                if not task.done():
                    task.cancel()
            results = await asyncio.gather(*polling_tasks_to_cancel, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    logger.error(f"StreamingManager Shutdown: Error from cancelled polling task {polling_tasks_to_cancel[i].get_name()}: {result}")
        
        logger.info("StreamingManager: Shutdown sequence complete.") #