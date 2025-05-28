# services/subscription_registry.py

import logging
from typing import Any, Dict, Set, Tuple, Optional

# It's good practice to use a logger named after the module or class.
# If your logging setup uses __name__, that's fine. Otherwise, you might prefer:
# logger = logging.getLogger("SubscriptionRegistry")
logger = logging.getLogger(__name__)

# A type alias for a subscription key.
# This tuple uniquely identifies a specific data stream view a client is interested in.
# Structure: (market_identifier, provider_identifier, symbol_identifier, timeframe_or_stream_type_identifier)
# Example: ('crypto', 'binance', 'BTC/USDT', '1m') for OHLCV
# Example: ('crypto', 'binance', 'ETH/USDT', 'trades') for trades stream
SubscriptionKey = Tuple[str, str, str, str]

class SubscriptionRegistry:
    """
    Tracks active WebSocket client subscriptions, allowing a single WebSocket
    connection to maintain multiple distinct subscriptions simultaneously.

    This registry is crucial for scenarios where a client needs to receive
    real-time updates for several different data streams (e.g., multiple
    charts, a chart and a trade feed) over the same WebSocket connection.

    Internal Data Structures:
      - _ws_to_keys (Dict[Any, Set[SubscriptionKey]]):
          Maps each WebSocket connection object (ws) to a set of
          SubscriptionKey tuples it is currently subscribed to.
          Example: { <WebSocketClient1>: {('crypto', 'binance', 'BTC/USDT', '1m'),
                                          ('crypto', 'binance', 'ETH/USDT', 'trades')},
                     <WebSocketClient2>: {('crypto', 'coinbase', 'BTC/USD', '5m')} }

      - _key_to_ws (Dict[SubscriptionKey, Set[Any]]):
          Maps each unique SubscriptionKey to a set of WebSocket connection
          objects that are currently subscribed to that specific key.
          Example: { ('crypto', 'binance', 'BTC/USDT', '1m'): {<WebSocketClient1>, <WebSocketClient3>},
                     ('crypto', 'binance', 'ETH/USDT', 'trades'): {<WebSocketClient1>} }
    """

    def __init__(self):
        """
        Initializes the SubscriptionRegistry with empty tracking dictionaries.
        """
        self._ws_to_keys: Dict[Any, Set[SubscriptionKey]] = {}
        self._key_to_ws: Dict[SubscriptionKey, Set[Any]] = {}
        logger.info("SubscriptionRegistry initialized (supports multiple subscriptions per WebSocket client).")

    def _generate_key(self, market: str, provider: str, symbol: str, timeframe_or_stream_type: str) -> SubscriptionKey:
        """
        Internal helper to generate a standardized SubscriptionKey tuple.
        It's expected that input arguments are already normalized (e.g., case, whitespace)
        by the calling service (like SubscriptionService) before this method is invoked.

        Args:
            market: The market identifier (e.g., "crypto", "us_equity").
            provider: The provider or exchange identifier (e.g., "binance", "alpaca").
            symbol: The trading symbol (e.g., "BTC/USDT", "AAPL").
            timeframe_or_stream_type: The timeframe (e.g., "1m", "1h") for OHLCV,
                                      or a string identifying the stream type (e.g., "trades", "user_orders").

        Returns:
            SubscriptionKey: The generated tuple.
        """
        # Assuming inputs are pre-normalized by the caller (SubscriptionService) for consistency.
        return (market, provider, symbol, timeframe_or_stream_type)

    def register(
        self,
        ws: Any, # WebSocket connection object (e.g., from Quart)
        market: str,
        provider: str,
        symbol: str,
        timeframe_or_stream_type: str,
    ) -> bool:
        """
        Registers a WebSocket client (`ws`) for a specific data subscription,
        identified by the combination of market, provider, symbol, and
        timeframe/stream_type.

        A single WebSocket client can be registered to multiple distinct subscription keys.
        This method is idempotent; registering an already registered ws/key combination
        will not cause errors or duplicate entries.

        Args:
            ws: The WebSocket connection object.
            market: Market identifier (e.g., "crypto"). Needs to be normalized by caller.
            provider: Provider identifier (e.g., "binance"). Needs to be normalized by caller.
            symbol: Trading symbol (e.g., "BTC/USDT"). Needs to be normalized by caller.
            timeframe_or_stream_type: Timeframe string (e.g., "1m") or a stream type
                                      identifier (e.g., "trades"). Needs to be normalized by caller.

        Returns:
            bool: True if this specific ws/key registration was new (i.e., the ws wasn't
                  already subscribed to this exact key), False otherwise.
        """
        key = self._generate_key(market, provider, symbol, timeframe_or_stream_type)
        ws_id_for_log = getattr(ws, 'id', id(ws)) # Get a consistent ID for logging

        # Ensure the WebSocket client has an entry in _ws_to_keys
        client_specific_keys = self._ws_to_keys.setdefault(ws, set())
        
        # Ensure the SubscriptionKey has an entry in _key_to_ws
        key_specific_subscribers = self._key_to_ws.setdefault(key, set())

        is_new_subscription_for_this_ws = key not in client_specific_keys
        if is_new_subscription_for_this_ws:
            client_specific_keys.add(key)
        
        is_new_subscriber_for_this_key = ws not in key_specific_subscribers
        if is_new_subscriber_for_this_key:
            key_specific_subscribers.add(ws)

        if is_new_subscription_for_this_ws: # Log only if it's a new addition for this client
            logger.debug(f"SubscriptionRegistry: Registered WebSocket {ws_id_for_log} for new key {key}.")
            return True
        else:
            logger.debug(f"SubscriptionRegistry: WebSocket {ws_id_for_log} was already registered for key {key}. Registration confirmed.")
            return False # Not a brand-new registration for this ws/key pair

    def unregister_specific(
        self,
        ws: Any,
        market: str,
        provider: str,
        symbol: str,
        timeframe_or_stream_type: str,
    ) -> bool:
        """
        Unregisters a WebSocket client (`ws`) from a single, specific subscription key.
        This does not affect other subscriptions the same WebSocket client might have.

        Args:
            ws: The WebSocket connection object.
            market: Market identifier of the subscription to remove.
            provider: Provider identifier of the subscription to remove.
            symbol: Trading symbol of the subscription to remove.
            timeframe_or_stream_type: Timeframe or stream type of the subscription to remove.

        Returns:
            bool: True if the specific subscription was found and removed for this WebSocket,
                  False otherwise (e.g., the WebSocket was not subscribed to this specific key).
        """
        key_to_remove = self._generate_key(market, provider, symbol, timeframe_or_stream_type)
        ws_id_for_log = getattr(ws, 'id', id(ws))
        
        key_was_present_for_ws = False
        if ws in self._ws_to_keys:
            if key_to_remove in self._ws_to_keys[ws]:
                self._ws_to_keys[ws].discard(key_to_remove)
                key_was_present_for_ws = True
                if not self._ws_to_keys[ws]:  # If this ws has no more subscriptions
                    del self._ws_to_keys[ws]   # Remove the ws entry itself
        
        ws_was_present_for_key = False
        if key_to_remove in self._key_to_ws:
            if ws in self._key_to_ws[key_to_remove]:
                self._key_to_ws[key_to_remove].discard(ws)
                ws_was_present_for_key = True
                if not self._key_to_ws[key_to_remove]:  # If this key has no more subscribers
                    del self._key_to_ws[key_to_remove]   # Remove the key entry itself

        if key_was_present_for_ws and ws_was_present_for_key:
            logger.debug(f"SubscriptionRegistry: Unregistered WebSocket {ws_id_for_log} from specific key {key_to_remove}.")
            return True
        elif key_was_present_for_ws or ws_was_present_for_key: # Data was partially inconsistent, log warning
            logger.warning(f"SubscriptionRegistry: Partially unregistered WebSocket {ws_id_for_log} from key {key_to_remove}. "
                           f"Present for WS: {key_was_present_for_ws}, Present for Key: {ws_was_present_for_key}. This might indicate an issue.")
            return True # Still report as successful if either part was done
        else:
            logger.debug(f"SubscriptionRegistry: WebSocket {ws_id_for_log} was not registered for specific key {key_to_remove}.")
            return False

    def unregister_all_for_ws(self, ws: Any) -> int:
        """
        Unregisters a WebSocket client (`ws`) from ALL its current subscriptions.
        This is typically called when a WebSocket connection is closed or terminated.

        Args:
            ws: The WebSocket connection object to unregister.

        Returns:
            int: The number of subscription keys the WebSocket was successfully unregistered from.
        """
        ws_id_for_log = getattr(ws, 'id', id(ws))
        
        # Retrieve all keys this WebSocket was subscribed to.
        # .pop() removes the entry for 'ws' from _ws_to_keys and returns its set of keys.
        # If 'ws' is not found, it returns an empty set.
        keys_associated_with_ws = self._ws_to_keys.pop(ws, set())
        
        count_removed = 0
        if not keys_associated_with_ws:
            logger.debug(f"SubscriptionRegistry: WebSocket {ws_id_for_log} had no registered keys to unregister.")
            return 0

        # For each key this WebSocket was subscribed to, remove the WebSocket from that key's subscriber list.
        for key in keys_associated_with_ws:
            if key in self._key_to_ws:
                if ws in self._key_to_ws[key]:
                    self._key_to_ws[key].discard(ws)
                    count_removed += 1
                if not self._key_to_ws[key]:  # If this key no longer has any subscribers
                    del self._key_to_ws[key]   # Remove the key entry itself
        
        if count_removed > 0:
            logger.debug(f"SubscriptionRegistry: Unregistered WebSocket {ws_id_for_log} from {count_removed} key(s): {keys_associated_with_ws}.")
        elif keys_associated_with_ws: # Should not happen if logic is correct and ws was in _ws_to_keys
             logger.warning(f"SubscriptionRegistry: WebSocket {ws_id_for_log} was in _ws_to_keys with "
                           f"{len(keys_associated_with_ws)} keys, but no corresponding entries were cleaned from _key_to_ws.")
        return count_removed

    def get_subscribers_for_key(
        self,
        market: str,
        provider: str,
        symbol: str,
        timeframe_or_stream_type: str,
    ) -> Set[Any]:
        """
        Returns the set of WebSocket clients currently subscribed to a specific data stream key.

        Args:
            market: Market identifier.
            provider: Provider identifier.
            symbol: Trading symbol.
            timeframe_or_stream_type: Timeframe or stream type identifier.

        Returns:
            Set[Any]: A new set containing WebSocket connection objects subscribed to the key.
                      Returns an empty set if no clients are subscribed to this key.
        """
        key = self._generate_key(market, provider, symbol, timeframe_or_stream_type)
        # Return a copy of the set to prevent external modification of the internal set.
        return set(self._key_to_ws.get(key, set()))

    def get_keys_for_ws(self, ws: Any) -> Set[SubscriptionKey]:
        """
        Returns all SubscriptionKeys a given WebSocket client is currently subscribed to.

        Args:
            ws: The WebSocket connection object.

        Returns:
            Set[SubscriptionKey]: A new set containing all subscription keys for the given WebSocket.
                                 Returns an empty set if the WebSocket has no active subscriptions.
        """
        # Return a copy of the set.
        return set(self._ws_to_keys.get(ws, set()))

    def get_all_active_keys(self) -> Set[SubscriptionKey]:
        """
        Retrieves a set of all unique subscription keys that currently have one or
        more active subscribers.

        Returns:
            Set[SubscriptionKey]: A new set containing all currently active subscription key tuples.
                                 Returns an empty set if there are no active subscriptions system-wide.
        """
        # Return a copy of the keys from the _key_to_ws dictionary.
        return set(self._key_to_ws.keys())

    def clear_all(self) -> None:
        """
        Clears all registrations from the registry.
        This is typically used during application shutdown or for resetting state.
        """
        self._ws_to_keys.clear()
        self._key_to_ws.clear()
        logger.info("SubscriptionRegistry: All registrations have been cleared.")