# plugins/__init__.py

import os
import importlib
import inspect
import logging
from typing import Callable, Dict, List, Type, Optional
from plugins.base import MarketPlugin, PluginError # Assuming base.py is in the same directory

logger = logging.getLogger("PluginLoader")

class PluginLoader:
    """
    Dynamically loads and manages market data plugins.
    Plugins are Python files in the 'plugins' directory that contain a class
    inheriting from MarketPlugin.
    """
    _instances: Dict[str, MarketPlugin] = {}
    _factories: Dict[str, Callable[[], MarketPlugin]] = {}
    _plugin_classes: Dict[str, Type[MarketPlugin]] = {}

    @classmethod
    def discover_plugins(cls, plugin_dir: str = None, base_module_path: str = "plugins"):
        """
        Discovers plugins from the specified directory.
        Each plugin file should contain a class that inherits from MarketPlugin.
        The plugin key can be defined by a 'plugin_key' class attribute in the plugin,
        or defaults to the filename (without _plugin.py or .py).

        :param plugin_dir: The directory to scan for plugins. Defaults to the directory
                           of this __init__.py file.
        :param base_module_path: The base Python module path for importing plugins (e.g., "plugins").
        """
        if cls._plugin_classes: # Discover only once
            return

        if plugin_dir is None:
            plugin_dir = os.path.dirname(__file__)

        logger.info(f"Discovering plugins in: {plugin_dir} with base module path: {base_module_path}")

        for filename in os.listdir(plugin_dir):
            if filename.endswith(".py") and filename not in ("__init__.py", "base.py"):
                module_name = filename[:-3]  # Remove .py
                full_module_path = f"{base_module_path}.{module_name}"
                try:
                    module = importlib.import_module(full_module_path)
                    for name, member in inspect.getmembers(module):
                        if inspect.isclass(member) and \
                           issubclass(member, MarketPlugin) and \
                           member is not MarketPlugin: # Ensure it's a subclass, not MarketPlugin itself
                            
                            plugin_key = getattr(member, "plugin_key", None)
                            if not plugin_key:
                                if module_name.endswith("_plugin"):
                                    plugin_key = module_name[:-7] # remove _plugin
                                else:
                                    plugin_key = module_name
                            
                            if plugin_key in cls._plugin_classes:
                                logger.warning(
                                    f"Duplicate plugin key '{plugin_key}' found in {full_module_path}. "
                                    f"Existing: {cls._plugin_classes[plugin_key]}. Skipping new one."
                                )
                                continue

                            cls._plugin_classes[plugin_key] = member
                            logger.info(f"Discovered plugin class '{member.__name__}' with key '{plugin_key}' from {full_module_path}")
                            
                            # Check if plugin requires eager loading or factory (e.g. based on a class attribute)
                            # For now, let's assume all dynamically discovered plugins use factories
                            # to handle potential initialization arguments like API keys.
                            cls._register_factory_for_discovered_plugin(plugin_key, member)

                except ImportError as e:
                    logger.error(f"Failed to import plugin module {full_module_path}: {e}", exc_info=True)
                except Exception as e:
                    logger.error(f"Error processing plugin file {filename}: {e}", exc_info=True)
        
        # Manually register CryptoPlugin as it's fundamental and always available without external keys for basic data
        # This can be removed if CryptoPlugin is also made to conform to the factory pattern completely.
        try:
            from .crypto import CryptoPlugin # Assuming crypto.py is in the same directory
            if "crypto" not in cls._plugin_classes and "crypto" not in cls._factories:
                 # CryptoPlugin typically doesn't need API keys for basic data listing,
                 # so it can be instantiated directly or via a simple factory.
                def _crypto_factory() -> CryptoPlugin:
                    return CryptoPlugin()
                cls.register_factory("crypto", _crypto_factory, CryptoPlugin)
                logger.info("Manually registered factory for built-in CryptoPlugin.")
        except ImportError:
            logger.error("CryptoPlugin could not be imported for manual registration.")


    @classmethod
    def _create_factory(cls, plugin_class: Type[MarketPlugin]) -> Callable[[], MarketPlugin]:
        """
        Creates a default factory for a plugin class.
        This factory will attempt to instantiate the plugin.
        If the plugin's __init__ requires arguments (like API keys),
        it should provide its own more specific factory or be designed
        to fetch credentials from environment variables within its __init__.
        """
        def factory() -> MarketPlugin:
            try:
                # Attempt to get API keys from environment if plugin is designed this way
                # This is a generic approach; specific plugins might need more tailored factories.
                api_key_env = f"{plugin_class.plugin_key.upper()}_API_KEY" if hasattr(plugin_class, 'plugin_key') else None
                api_secret_env = f"{plugin_class.plugin_key.upper()}_API_SECRET" if hasattr(plugin_class, 'plugin_key') else None
                
                api_key = os.getenv(api_key_env) if api_key_env else None
                api_secret = os.getenv(api_secret_env) if api_secret_env else None

                # Check __init__ signature for required args
                sig = inspect.signature(plugin_class.__init__)
                params = sig.parameters
                
                # Simplified: if keys are expected and found, pass them.
                # A more robust way is for plugins to handle their own config or provide specific factories.
                if 'api_key' in params and 'api_secret' in params and api_key and api_secret:
                    logger.info(f"Instantiating {plugin_class.__name__} with API key and secret from env.")
                    return plugin_class(api_key=api_key, api_secret=api_secret)
                elif 'api_key' in params and api_key: # Only API key
                    logger.info(f"Instantiating {plugin_class.__name__} with API key from env.")
                    return plugin_class(api_key=api_key)
                else: # No specific args known, or keys not found
                    logger.info(f"Instantiating {plugin_class.__name__} with no arguments (or it handles its own config).")
                    return plugin_class()
            except Exception as e:
                logger.error(f"Error instantiating plugin {plugin_class.__name__} via default factory: {e}", exc_info=True)
                raise PluginError(f"Failed to create plugin instance for {plugin_class.__name__}: {e}") from e
        return factory

    @classmethod
    def _register_factory_for_discovered_plugin(cls, key: str, plugin_class: Type[MarketPlugin]):
        """Helper to register a factory for a discovered plugin class."""
        if key in cls._factories:
            logger.warning(f"Factory for plugin key '{key}' already registered. Skipping.")
            return
        
        # More sophisticated plugins might have a static method like `get_factory()`
        if hasattr(plugin_class, "get_factory") and callable(getattr(plugin_class, "get_factory")):
            factory = plugin_class.get_factory()
            logger.info(f"Using custom factory provided by plugin '{key}'.")
        else:
            # Create a generic factory. This assumes the plugin can be instantiated
            # without arguments or handles its own configuration (e.g., from env vars).
            factory = cls._create_factory(plugin_class)
            logger.info(f"Using generic factory for plugin '{key}'. Plugin should handle its own config if needed.")
        
        cls.register_factory(key, factory, plugin_class)


    @classmethod
    def register_factory(cls, key: str, factory: Callable[[], MarketPlugin], plugin_class: Optional[Type[MarketPlugin]] = None):
        """Registers a factory function that creates a plugin instance."""
        if key in cls._factories or key in cls._instances:
            logger.warning(f"Plugin or factory for key '{key}' already registered. Overwriting factory.")
        cls._factories[key] = factory
        if plugin_class: # Store the class type if provided
            cls._plugin_classes[key] = plugin_class
        logger.info(f"Registered plugin factory for key '{key}'")

    @classmethod
    def register_plugin_instance(cls, key: str, plugin_instance: MarketPlugin):
        """Registers an already created plugin instance (less common for dynamic loading)."""
        if key in cls._factories or key in cls._instances:
            logger.warning(f"Plugin or factory for key '{key}' already registered. Overwriting instance.")
        cls._instances[key] = plugin_instance
        cls._plugin_classes[key] = type(plugin_instance) # Store its class
        logger.info(f"Registered plugin instance for key '{key}'")

    @classmethod
    def load_plugin(cls, key: str) -> MarketPlugin:
        """
        Loads a plugin by its key.
        If an instance exists, it's returned. Otherwise, uses a factory if available.
        """
        if key in cls._instances:
            return cls._instances[key]
        
        if key in cls._factories:
            try:
                logger.info(f"Creating plugin instance for '{key}' using its factory.")
                plugin_instance = cls._factories[key]()
                cls._instances[key] = plugin_instance # Cache the instance
                return plugin_instance
            except Exception as e:
                logger.error(f"Factory for plugin '{key}' failed to create instance: {e}", exc_info=True)
                raise PluginError(f"Factory for plugin '{key}' failed: {e}") from e
        
        # If discovery hasn't run or didn't find it, and no manual registration
        if not cls._plugin_classes and not cls._factories and not cls._instances:
             logger.warning("Plugin discovery has not been run. Attempting now.")
             cls.discover_plugins() # Attempt discovery if not done
             # Retry loading after discovery
             if key in cls._factories: # Check again if discovery populated it
                return cls.load_plugin(key)


        logger.error(f"No plugin instance or factory registered for key '{key}'. Known factories: {list(cls._factories.keys())}")
        raise PluginError(f"No plugin registered under key '{key}'")

    @classmethod
    def list_plugins(cls) -> List[str]:
        """Returns a list of keys for all discoverable/registered plugins."""
        # Ensure discovery has run to populate _plugin_classes and _factories from files
        if not cls._plugin_classes and not cls._factories: # A bit simplistic, might need better "is_discovered" flag
            cls.discover_plugins()
        return list(set(cls._instances.keys()) | set(cls._factories.keys()) | set(cls._plugin_classes.keys()))

    @classmethod
    def get_plugin_class(cls, key: str) -> Optional[Type[MarketPlugin]]:
        """Returns the class type of a registered plugin, if known."""
        return cls._plugin_classes.get(key)

# Perform plugin discovery when this module is loaded.
# The application should call discover_plugins() explicitly at startup,
# ideally from app.py or app_extensions/__init__.py, to control when it happens.
# PluginLoader.discover_plugins() # Auto-discovery at import time.
# It's generally better to call this explicitly from your app's startup sequence.
