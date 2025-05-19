# services/subscription_registry.py

import logging
from typing import Any, Dict, Set, Tuple, Optional

logger = logging.getLogger("SubscriptionRegistry")

# A tuple identifying a subscription: (market, provider, symbol, timeframe)
SubscriptionKey = Tuple[str, str, str, str]

class SubscriptionRegistry:
    """
    Tracks active WebSocket subscriptions:
      - _ws_to_key maps each WebSocket connection to its SubscriptionKey
      - _key_to_ws maps each SubscriptionKey to a set of WebSocket connections
    """
    def __init__(self):
        # ws -> (market, provider, symbol, timeframe)
        self._ws_to_key: Dict[Any, SubscriptionKey] = {}
        # (market, provider, symbol, timeframe) -> set of ws
        self._key_to_ws: Dict[SubscriptionKey, Set[Any]] = {}

    def register(
        self,
        ws: Any,
        market: str,
        provider: str,
        symbol: str,
        timeframe: str,
    ) -> None:
        """
        Register a WebSocket 'ws' for the given subscription parameters.
        If the ws was already registered, it is first unregistered.

        :param ws: WebSocket connection object (e.g. Quart Websocket)
        :param market: e.g. "crypto", "stocks"
        :param provider: plugin/provider name, e.g. "bitstamp"
        :param symbol: trading symbol, e.g. "BTC/USD"
        :param timeframe: timeframe string, e.g. "1m", "5m"
        """
        key = (market, provider, symbol, timeframe)
        # If ws already had a subscription, remove it
        if ws in self._ws_to_key:
            self.unregister(ws)

        # Map ws to key
        self._ws_to_key[ws] = key
        # Add ws to the set of subscribers for this key
        subscribers = self._key_to_ws.setdefault(key, set())
        subscribers.add(ws)
        logger.debug(f"SubscriptionRegistry: registered {ws} for {key}")

    def unregister(self, ws: Any) -> None:
        """
        Unregister a WebSocket 'ws' from its subscription, if any.

        :param ws: WebSocket connection object to remove
        """
        key = self._ws_to_key.pop(ws, None)
        if not key:
            return
        subscribers = self._key_to_ws.get(key)
        if subscribers:
            subscribers.discard(ws)
            if not subscribers:
                # Clean up empty subscription key
                del self._key_to_ws[key]
        logger.debug(f"SubscriptionRegistry: unregistered {ws} from {key}")

    def get_subscribers(
        self,
        market: str,
        provider: str,
        symbol: str,
        timeframe: str,
    ) -> Set[Any]:
        """
        Return the set of WebSocket connections subscribed to the given key.

        :returns: set of ws, or empty set if none
        """
        key = (market, provider, symbol, timeframe)
        return set(self._key_to_ws.get(key, set()))

    def get_all_keys(self) -> Set[SubscriptionKey]:
        """
        Retrieves all unique subscription keys that currently have active subscribers.

        A subscription key is a tuple that uniquely identifies a specific data stream,
        typically in the format: (market, provider, symbol, timeframe).

        Returns:
            Set[SubscriptionKey]: A set containing all active subscription key tuples.
                                  Returns an empty set if no subscriptions are active.
        """
        return set(self._key_to_ws.keys())

    def get_key_for_ws(self, ws: Any) -> Optional[SubscriptionKey]:
        """
        Return the SubscriptionKey (market,provider,symbol,timeframe)
        for a given WebSocket, or None if not registered.
        """
        return self._ws_to_key.get(ws)

    def clear_all(self) -> None:
        """
        Clears all registrations from the registry.
        """
        self._ws_to_key.clear()
        self._key_to_ws.clear()
        logger.info("SubscriptionRegistry: All registrations cleared.")