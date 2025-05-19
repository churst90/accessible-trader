# plugins/__init__.py

import os
import logging
from typing import Callable, Dict, List

from plugins.base import MarketPlugin, PluginError
from plugins.crypto import CryptoPlugin
from plugins.alpaca import AlpacaPlugin

logger = logging.getLogger("PluginLoader")


class PluginLoader:
    # instantiated plugins
    _instances: Dict[str, MarketPlugin] = {}
    # lazy factories for plugins not created at import
    _factories: Dict[str, Callable[[], MarketPlugin]] = {}

    @classmethod
    def register_plugin(cls, key: str, plugin: MarketPlugin):
        cls._instances[key] = plugin
        logger.info(f"Registered plugin instance for key '{key}'")

    @classmethod
    def register_factory(cls, key: str, factory: Callable[[], MarketPlugin]):
        cls._factories[key] = factory
        logger.info(f"Registered plugin factory for key '{key}'")

    @classmethod
    def load_plugin(cls, key: str) -> MarketPlugin:
        # return existing instance
        if key in cls._instances:
            return cls._instances[key]
        # otherwise try factory
        if key in cls._factories:
            plugin = cls._factories[key]()
            cls._instances[key] = plugin
            return plugin
        raise PluginError(f"No plugin registered under '{key}'")

    @classmethod
    def list_plugins(cls) -> List[str]:
        # keys that are either instantiated or factory-registered
        return list(set(cls._instances.keys()) | set(cls._factories.keys()))


# 1) CryptoPlugin is always available
crypto_plugin = CryptoPlugin()
PluginLoader.register_plugin("crypto", crypto_plugin)

# 2) AlpacaPlugin: lazy factory to avoid crashing at import time
def _alpaca_factory() -> MarketPlugin:
    api_key    = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")
    if not (api_key and api_secret):
        raise PluginError("Alpaca credentials must be set in environment")
    return AlpacaPlugin(api_key=api_key, api_secret=api_secret)

PluginLoader.register_factory("alpaca", _alpaca_factory)
