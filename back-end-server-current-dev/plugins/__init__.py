# plugins/__init__.py

import os
import importlib
import inspect
import logging
from typing import Dict, List, Type, Optional # Removed unused Callable, Coroutine

from plugins.base import MarketPlugin # Import the base class for type checking and issubclass

# Standard logger name for the module
logger = logging.getLogger(__name__)

class PluginLoader:
    """
    Dynamically discovers and manages MarketPlugin *classes*.

    This class scans the 'plugins' directory (or a specified directory) for
    Python modules containing classes that inherit from `MarketPlugin`.
    It registers these plugin classes using their `plugin_key` (a mandatory
    class attribute defined in `MarketPlugin` and its subclasses).

    Furthermore, it builds a mapping from market names (e.g., "crypto", "stocks")
    to the `plugin_key` of the plugin class responsible for handling that market.
    This mapping is derived from the `supported_markets` class attribute of each
    discovered plugin.

    The PluginLoader is designed to be used primarily through its class methods
    and typically performs discovery once at application startup.
    """

    # Stores discovered plugin classes, keyed by their unique `plugin_key`.
    # e.g., {"crypto": CryptoPluginClass, "alpaca": AlpacaPluginClass}
    _plugin_classes: Dict[str, Type[MarketPlugin]] = {}

    # Stores a mapping from a market name (lowercase) to the `plugin_key`
    # of the plugin class that handles it.
    # e.g., {"crypto": "crypto", "stocks": "alpaca", "us_equity": "alpaca"}
    _market_to_plugin_key_map: Dict[str, str] = {}

    @classmethod
    def discover_plugins(cls, plugin_dir: Optional[str] = None, base_module_path: str = "plugins") -> None:
        """
        Discovers `MarketPlugin` classes from Python files in the specified directory
        and registers them along with the markets they support.

        This method scans Python files (excluding `__init__.py` and `base.py`)
        for classes that are subclasses of `MarketPlugin`. It uses the
        `get_plugin_key()` class method for registration and the
        `get_supported_markets()` class method to build the market-to-plugin mapping.

        This method is designed to be called once during application startup but
        is idempotent and can be called again if `clear_plugins` was used.

        Args:
            plugin_dir (Optional[str]): The absolute directory path to scan for plugin modules.
                                        Defaults to the directory of this `plugins` package.
            base_module_path (str): The base Python module path used for importing the
                                    plugin modules (e.g., "plugins" if plugin files
                                    are in the 'plugins/' directory relative to the project root).
        """
        # Check if discovery has already run and populated the maps.
        # This prevents re-scanning unless explicitly cleared.
        if cls._plugin_classes and cls._market_to_plugin_key_map:
            logger.debug("Plugin discovery has already been performed. Skipping re-discovery.")
            return

        # Clear any previous state in case of a forced re-discovery.
        cls._plugin_classes.clear()
        cls._market_to_plugin_key_map.clear()

        if plugin_dir is None:
            plugin_dir = os.path.dirname(__file__) # Defaults to the 'plugins' directory itself

        logger.info(f"Discovering plugin classes in directory: {plugin_dir} (using base module path: {base_module_path})")

        for filename in os.listdir(plugin_dir):
            if filename.endswith(".py") and filename not in ("__init__.py", "base.py"):
                module_name_only = filename[:-3]  # Remove .py extension
                full_module_import_path = f"{base_module_path}.{module_name_only}"
                
                try:
                    module = importlib.import_module(full_module_import_path)
                    for member_name, plugin_class_candidate in inspect.getmembers(module):
                        # Check if it's a class, a subclass of MarketPlugin, and not MarketPlugin itself.
                        if inspect.isclass(plugin_class_candidate) and \
                           issubclass(plugin_class_candidate, MarketPlugin) and \
                           plugin_class_candidate is not MarketPlugin:
                            
                            try:
                                # Retrieve plugin_key from the class method.
                                current_plugin_key = plugin_class_candidate.get_plugin_key()
                                if not current_plugin_key:
                                     logger.warning(f"Plugin class '{plugin_class_candidate.__name__}' in {full_module_import_path} returned an empty plugin_key. Skipping.")
                                     continue
                            except NotImplementedError as e:
                                logger.warning(f"Plugin class '{plugin_class_candidate.__name__}' in {full_module_import_path} failed to provide plugin_key: {e}. Skipping.")
                                continue
                            
                            # Check for duplicate plugin keys.
                            if current_plugin_key in cls._plugin_classes:
                                logger.warning(
                                    f"Duplicate plugin key '{current_plugin_key}' found from '{full_module_import_path}'. "
                                    f"Already registered by class '{cls._plugin_classes[current_plugin_key].__name__}'. Skipping new one."
                                )
                                continue

                            # Register the plugin class.
                            cls._plugin_classes[current_plugin_key] = plugin_class_candidate
                            logger.info(f"Discovered plugin class '{plugin_class_candidate.__name__}' registered with key '{current_plugin_key}' from {full_module_import_path}")

                            # Populate market_to_plugin_key_map.
                            try:
                                supported_markets_list = plugin_class_candidate.get_supported_markets()
                                if not isinstance(supported_markets_list, list) or \
                                   not all(isinstance(m, str) for m in supported_markets_list):
                                    logger.warning(
                                        f"Plugin class '{plugin_class_candidate.__name__}' (key: {current_plugin_key}) "
                                        f"has invalid 'supported_markets' (must be List[str]). Skipping market mapping for it."
                                    )
                                    continue
                            except NotImplementedError as e:
                                logger.warning(f"Plugin class '{plugin_class_candidate.__name__}' (key: {current_plugin_key}) failed to provide supported_markets: {e}. Skipping market mapping.")
                                continue


                            for market_name_str in supported_markets_list:
                                market_name_lower = market_name_str.lower()
                                if market_name_lower in cls._market_to_plugin_key_map:
                                    # Conflict: another plugin already claims this market.
                                    existing_plugin_key = cls._market_to_plugin_key_map[market_name_lower]
                                    if existing_plugin_key != current_plugin_key: # Only warn if it's a *different* plugin
                                        logger.warning(
                                            f"Market Conflict: Market '{market_name_lower}' is already mapped to plugin '{existing_plugin_key}'. "
                                            f"Plugin '{current_plugin_key}' also claims to support it. "
                                            f"The first encountered mapping ('{existing_plugin_key}') will be used for this market."
                                        )
                                else:
                                    # New market mapping.
                                    cls._market_to_plugin_key_map[market_name_lower] = current_plugin_key
                                    logger.info(f"Market '{market_name_lower}' mapped to plugin key '{current_plugin_key}'.")

                except ImportError as e:
                    logger.error(f"Failed to import plugin module '{full_module_import_path}': {e}", exc_info=True)
                except Exception as e: # Catch other errors during module processing.
                    logger.error(f"Unexpected error processing plugin file '{filename}' (module '{full_module_import_path}'): {e}", exc_info=True)
        
        logger.info(
            f"Plugin discovery complete. Total registered plugin classes: {len(cls._plugin_classes)}. "
            f"Market map: {cls._market_to_plugin_key_map}"
        )

    @classmethod
    def get_plugin_class_by_key(cls, key: str) -> Optional[Type[MarketPlugin]]:
        """
        Retrieves a `MarketPlugin` class by its registered `plugin_key`.

        Ensures plugin discovery has run at least once.

        Args:
            key (str): The unique identifier (plugin_key) of the plugin class.

        Returns:
            Optional[Type[MarketPlugin]]: The MarketPlugin class, or None if not found.
        """
        if not cls._plugin_classes: # If called before explicit discovery
            logger.info("Plugin classes not yet discovered. Performing auto-discovery for get_plugin_class_by_key.")
            cls.discover_plugins()
        
        plugin_class = cls._plugin_classes.get(key)
        if plugin_class:
            logger.debug(f"Retrieved plugin class '{plugin_class.__name__}' for key '{key}'.")
        else:
            logger.error(f"No plugin class registered under key '{key}'. Available keys: {list(cls._plugin_classes.keys())}")
        return plugin_class

    @classmethod
    def get_plugin_key_for_market(cls, market_name: str) -> Optional[str]:
        """
        Gets the `plugin_key` of the plugin registered to handle the given market name.

        Ensures plugin discovery has run at least once. Market names are treated case-insensitively.

        Args:
            market_name (str): The name of the market (e.g., "crypto", "stocks").

        Returns:
            Optional[str]: The `plugin_key` string, or None if no plugin is registered for the market.
        """
        if not cls._market_to_plugin_key_map: # If called before explicit discovery
            logger.info("Market-to-plugin map not yet populated. Performing auto-discovery for get_plugin_key_for_market.")
            cls.discover_plugins()
        
        return cls._market_to_plugin_key_map.get(market_name.lower())

    @classmethod
    def get_all_markets(cls) -> List[str]:
        """
        Returns a sorted list of all unique market names discovered from all plugins.

        Ensures plugin discovery has run at least once.
        """
        if not cls._market_to_plugin_key_map: # If called before explicit discovery
            logger.info("Market list not yet populated. Performing auto-discovery for get_all_markets.")
            cls.discover_plugins()
        return sorted(list(cls._market_to_plugin_key_map.keys()))

    @classmethod
    def list_plugins(cls) -> List[str]:
        """
        Returns a sorted list of keys for all discovered and registered plugin classes.

        Ensures plugin discovery has run at least once.
        """
        if not cls._plugin_classes:
            logger.info("Plugin list not yet populated. Performing auto-discovery for list_plugins.")
            cls.discover_plugins()
        return sorted(list(cls._plugin_classes.keys()))

    @classmethod
    def clear_plugins(cls) -> None:
        """
        Clears all registered plugin classes and market mappings from the PluginLoader.
        Useful for testing or re-initialization scenarios.
        """
        cls._plugin_classes.clear()
        cls._market_to_plugin_key_map.clear()
        logger.info("All registered plugin classes and market mappings have been cleared from PluginLoader.")