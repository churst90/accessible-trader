# plugins/__init__.py

import os
import importlib
import inspect
import logging
from typing import Dict, List, Type, Optional

from plugins.base import MarketPlugin

logger = logging.getLogger(__name__)

class PluginLoader:
    _plugin_classes: Dict[str, Type[MarketPlugin]] = {}
    # MODIFIED: Store a list of plugin keys for each market
    _market_to_plugin_keys_map: Dict[str, List[str]] = {} # Renamed and type changed

    @classmethod
    def discover_plugins(cls, plugin_dir: Optional[str] = None, base_module_path: str = "plugins") -> None:
        if cls._plugin_classes and cls._market_to_plugin_keys_map: # Check new map name
            logger.debug("Plugin discovery has already been performed. Skipping re-discovery.")
            return

        cls._plugin_classes.clear()
        cls._market_to_plugin_keys_map.clear() # Clear new map name

        if plugin_dir is None:
            plugin_dir = os.path.dirname(__file__)

        logger.info(f"Discovering plugin classes in directory: {plugin_dir} (using base module path: {base_module_path})")

        for filename in os.listdir(plugin_dir):
            if filename.endswith(".py") and filename not in ("__init__.py", "base.py"):
                module_name_only = filename[:-3]
                full_module_import_path = f"{base_module_path}.{module_name_only}"
                
                try:
                    module = importlib.import_module(full_module_import_path)
                    for member_name, plugin_class_candidate in inspect.getmembers(module):
                        if inspect.isclass(plugin_class_candidate) and \
                           issubclass(plugin_class_candidate, MarketPlugin) and \
                           plugin_class_candidate is not MarketPlugin:
                            
                            try:
                                current_plugin_key = plugin_class_candidate.get_plugin_key()
                                if not current_plugin_key:
                                    logger.warning(f"Plugin class '{plugin_class_candidate.__name__}' in {full_module_import_path} returned an empty plugin_key. Skipping.")
                                    continue
                            except NotImplementedError as e:
                                logger.warning(f"Plugin class '{plugin_class_candidate.__name__}' in {full_module_import_path} failed to provide plugin_key: {e}. Skipping.")
                                continue
                            
                            if current_plugin_key in cls._plugin_classes:
                                logger.warning(
                                    f"Duplicate plugin key '{current_plugin_key}' found from '{full_module_import_path}'. "
                                    f"Already registered by class '{cls._plugin_classes[current_plugin_key].__name__}'. Skipping new one."
                                )
                                continue

                            cls._plugin_classes[current_plugin_key] = plugin_class_candidate
                            logger.info(f"Discovered plugin class '{plugin_class_candidate.__name__}' registered with key '{current_plugin_key}' from {full_module_import_path}")

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
                                # MODIFIED: Append plugin key to a list for the market
                                if market_name_lower not in cls._market_to_plugin_keys_map:
                                    cls._market_to_plugin_keys_map[market_name_lower] = []
                                
                                # Ensure a plugin key is not added multiple times for the same market
                                # (e.g., if a plugin erroneously lists the same market twice)
                                if current_plugin_key not in cls._market_to_plugin_keys_map[market_name_lower]:
                                    cls._market_to_plugin_keys_map[market_name_lower].append(current_plugin_key)
                                    logger.info(f"Market '{market_name_lower}' mapped to plugin key '{current_plugin_key}'.")
                                else:
                                    logger.debug(f"Plugin key '{current_plugin_key}' already mapped for market '{market_name_lower}'.")

                except ImportError as e:
                    logger.error(f"Failed to import plugin module '{full_module_import_path}': {e}", exc_info=True)
                except Exception as e:
                    logger.error(f"Unexpected error processing plugin file '{filename}' (module '{full_module_import_path}'): {e}", exc_info=True)
        
        logger.info(
            f"Plugin discovery complete. Total registered plugin classes: {len(cls._plugin_classes)}. "
            f"Market to plugin keys map: {cls._market_to_plugin_keys_map}" # Updated log
        )

    @classmethod
    def get_plugin_class_by_key(cls, key: str) -> Optional[Type[MarketPlugin]]:
        if not cls._plugin_classes:
            logger.info("Plugin classes not yet discovered. Performing auto-discovery for get_plugin_class_by_key.")
            cls.discover_plugins()
        
        plugin_class = cls._plugin_classes.get(key)
        if plugin_class:
            logger.debug(f"Retrieved plugin class '{plugin_class.__name__}' for key '{key}'.")
        else:
            logger.warning(f"No plugin class registered under key '{key}'. Available keys: {list(cls._plugin_classes.keys())}") # Changed to warning
        return plugin_class

    @classmethod # MODIFIED: Renamed and returns List[str]
    def get_plugin_keys_for_market(cls, market_name: str) -> List[str]:
        """
        Gets the list of `plugin_key`s of plugins registered to handle the given market name.
        """
        if not cls._market_to_plugin_keys_map: # Check new map name
            logger.info("Market-to-plugin map not yet populated. Performing auto-discovery for get_plugin_keys_for_market.")
            cls.discover_plugins()
        
        return cls._market_to_plugin_keys_map.get(market_name.lower(), []) # Return empty list if not found

    @classmethod
    def get_all_markets(cls) -> List[str]:
        if not cls._market_to_plugin_keys_map: # Check new map name
            logger.info("Market list not yet populated. Performing auto-discovery for get_all_markets.")
            cls.discover_plugins()
        return sorted(list(cls._market_to_plugin_keys_map.keys()))

    @classmethod
    def list_plugins(cls) -> List[str]:
        if not cls._plugin_classes:
            logger.info("Plugin list not yet populated. Performing auto-discovery for list_plugins.")
            cls.discover_plugins()
        return sorted(list(cls._plugin_classes.keys()))

    @classmethod
    def clear_plugins(cls) -> None:
        cls._plugin_classes.clear()
        cls._market_to_plugin_keys_map.clear() # Clear new map name
        logger.info("All registered plugin classes and market mappings have been cleared from PluginLoader.")