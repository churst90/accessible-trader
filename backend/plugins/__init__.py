from plugins.crypto import CryptoPlugin
import logging

logger = logging.getLogger("PluginLoader")

class PluginLoader:
    """
    Centralized manager for loading and accessing market plugins.
    """
    _plugins = {}

    @classmethod
    def register_plugin(cls, market_name, plugin_instance):
        """
        Register a new plugin with the loader.
        :param market_name: The name of the market (e.g., 'crypto').
        :param plugin_instance: The plugin instance to register.
        """
        if market_name in cls._plugins:
            logger.warning(f"Plugin for market '{market_name}' is already registered. Overwriting.")
        cls._plugins[market_name] = plugin_instance
        logger.info(f"Plugin for market '{market_name}' registered successfully.")

    @classmethod
    def load_plugin(cls, market_name):
        """
        Retrieve the plugin instance for a given market.
        :param market_name: The name of the market.
        :return: The plugin instance.
        :raises ValueError: If the plugin for the market is not registered.
        """
        plugin = cls._plugins.get(market_name)
        if not plugin:
            logger.error(f"No plugin available for market '{market_name}'.")
            raise ValueError(f"No plugin available for market '{market_name}'")
        logger.debug(f"Plugin for market '{market_name}' loaded successfully.")
        return plugin

    @classmethod
    def list_plugins(cls):
        """
        List all registered plugins.
        :return: A dictionary of all registered plugins.
        """
        logger.debug("Listing all registered plugins.")
        return cls._plugins


# Register the initial set of plugins
PluginLoader.register_plugin("crypto", CryptoPlugin())


# Alias for load_plugin to match expected naming in other parts of the code
load_market_plugin = PluginLoader.load_plugin
