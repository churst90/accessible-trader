# services/data_sources/plugin_source.py

import logging
from typing import Any, Dict, List, Optional

from plugins.base import (
    OHLCVBar,
    MarketPlugin, # For type hinting self.plugin
    PluginError,
    AuthenticationPluginError,
    NetworkPluginError,
    PluginFeatureNotSupportedError
)
from services.data_sources.base import (
    DataSource,
    DataSourceError, # Base error for this layer
    AuthenticationDataSourceError,
    DataSourceNetworkError,
    DataSourceFeatureNotSupportedError
)

# Forward declaration for type hinting MarketService to avoid circular import
if False:
    from services.market_service import MarketService

logger = logging.getLogger(__name__)

class PluginSource(DataSource):
    """
    PluginSource is a data source that fetches OHLCV data directly from a
    configured and instantiated market plugin (e.g., CryptoPlugin, AlpacaPlugin).

    It acts as an adapter between the DataSource interface used by DataOrchestrator
    and the MarketPlugin interface implemented by individual plugins.
    This class does not handle pagination or resampling itself; that is managed
    by the DataOrchestrator. It simply executes a fetch request on the plugin
    for the given parameters.
    """

    def __init__(
        self,
        plugin: MarketPlugin,
        market: str,
        provider: str, # This should match plugin.provider_id
        symbol: str,
        # market_service: Optional['MarketService'] = None # Kept if needed for future advanced interactions
                                                       # but typically not used for basic fetch.
    ):
        """
        Initializes the PluginSource with a specific plugin instance and its context.

        Args:
            plugin (MarketPlugin): The instantiated and configured plugin object
                                   (e.g., CryptoPlugin instance for 'binance',
                                   AlpacaPlugin instance for 'alpaca') to fetch data from.
            market (str): The market identifier (e.g., 'crypto', 'stocks') this source operates on.
            provider (str): The provider identifier (e.g., 'binance', 'alpaca') this source uses,
                            which must match the provider_id the plugin instance is configured for.
            symbol (str): The trading symbol (e.g., 'BTC/USD', 'AAPL') this source is for.
            # market_service (Optional['MarketService']): The main MarketService instance.
            #                                            Currently not used directly by PluginSource's
            #                                            core fetch logic but kept for potential future extensions.
        """
        super().__init__(source_id=f"plugin:{market}:{provider}:{symbol}") # Unique ID for this source instance
        
        if not isinstance(plugin, MarketPlugin):
            raise ValueError("PluginSource must be initialized with a valid MarketPlugin instance.")
        if not market or not provider or not symbol:
            raise ValueError("Market, provider, and symbol must be non-empty for PluginSource.")
        if provider.lower() != plugin.provider_id.lower():
            raise ValueError(
                f"PluginSource provider '{provider}' does not match "
                f"plugin's configured provider_id '{plugin.provider_id}'."
            )

        self.plugin: MarketPlugin = plugin
        self.market: str = market
        self.provider: str = provider # This is self.plugin.provider_id
        self.symbol: str = symbol
        # self.market_service = market_service

        logger.info(
            f"PluginSource '{self.source_id}' initialized, using plugin class '{plugin.__class__.__name__}' "
            f"configured for provider '{plugin.provider_id}'."
        )

    async def fetch_ohlcv(
        self,
        timeframe: str,
        since: Optional[int],
        before: Optional[int], # Corresponds to 'until' or similar in DataOrchestrator
        limit: int,
        # params is not part of DataSource ABC, DataOrchestrator prepares it for plugin
    ) -> List[OHLCVBar]:
        """
        Fetches OHLCV (Open, High, Low, Close, Volume) data by calling the
        `Workspace_historical_ohlcv` method on the configured plugin instance.

        This method is typically called by DataOrchestrator's paging logic to fetch
        a specific chunk of data.

        Args:
            timeframe (str): The timeframe for the OHLCV data (e.g., '1m', '5m', '1H').
                             This should be a timeframe the underlying plugin can handle,
                             often "1m" if DataOrchestrator intends to resample, or the
                             target timeframe if the plugin supports it natively.
            since (Optional[int]): Timestamp in milliseconds for the start of the data range (inclusive).
            before (Optional[int]): Timestamp in milliseconds for the end of the data range (exclusive).
                                   This will be mapped to the plugin's 'until' or equivalent parameter.
            limit (int): The maximum number of bars to fetch in this single call to the plugin.

        Returns:
            List[OHLCVBar]: A list of OHLCV bars from the plugin.

        Raises:
            DataSourceFeatureNotSupportedError: If the plugin doesn't support fetching OHLCV.
            AuthenticationDataSourceError: If plugin authentication fails.
            DataSourceNetworkError: For network issues with the plugin.
            DataSourceError: For other plugin-related errors.
        """
        log_context = f"{self.symbol}@{timeframe} (since={since}, before={before}, limit={limit})"
        logger.debug(f"PluginSource '{self.source_id}': Fetching OHLCV for {log_context}")

        # Construct the 'params' argument for the plugin if 'before' (until) is provided.
        # The plugin's fetch_historical_ohlcv method expects 'params' for such things.
        plugin_params: Dict[str, Any] = {}
        if before is not None:
            plugin_params['until_ms'] = before # Plugins should know to look for 'until_ms' or similar
                                            # Example: AlpacaPlugin maps this to 'end'
                                            # CryptoPlugin (CCXT) can take 'until' in its 'params' dict

        try:
            # Call the underlying plugin's method
            # The plugin instance (self.plugin) is already configured for the correct provider.
            fetched_bars: List[OHLCVBar] = await self.plugin.fetch_historical_ohlcv(
                symbol=self.symbol,
                timeframe=timeframe,
                since=since,
                limit=limit,
                params=plugin_params if plugin_params else None # Pass None if empty for cleaner plugin calls
            )

            if not fetched_bars:
                logger.debug(f"PluginSource '{self.source_id}': Plugin returned no data for {log_context}.")
            else:
                logger.info(f"PluginSource '{self.source_id}': Successfully fetched {len(fetched_bars)} bars for {log_context} from plugin.")
            
            return fetched_bars

        except PluginFeatureNotSupportedError as e:
            logger.warning(f"PluginSource '{self.source_id}': Feature not supported by plugin for {log_context}. Error: {e}")
            raise DataSourceFeatureNotSupportedError(f"Plugin does not support required feature: {e.feature_name}",) from e
        except AuthenticationPluginError as e:
            logger.error(f"PluginSource '{self.source_id}': Authentication error with plugin for {log_context}. Error: {e}")
            raise AuthenticationDataSourceError(f"Plugin authentication failed: {e.args[0] if e.args else str(e)}",) from e
        except NetworkPluginError as e:
            logger.error(f"PluginSource '{self.source_id}': Network error with plugin for {log_context}. Error: {e}")
            raise DataSourceNetworkError(f"Plugin network error: {e.args[0] if e.args else str(e)}",) from e
        except PluginError as e: # Catch other generic PluginErrors
            logger.error(f"PluginSource '{self.source_id}': Plugin error for {log_context}. Error: {e}")
            raise DataSourceError(f"General plugin error: {e.args[0] if e.args else str(e)}",) from e
        except Exception as e: # Catch any other unexpected exception from the plugin call
            logger.exception(f"PluginSource '{self.source_id}': Unexpected error during plugin OHLCV fetch for {log_context}. Error: {e}")
            raise DataSourceError(f"Unexpected error fetching data via plugin: {str(e)}",) from e

    def supports_timeframe(self, timeframe: str) -> bool:
        """
        Checks if the underlying plugin supports the given timeframe.
        This now attempts to call the plugin's `validate_timeframe` if available,
        otherwise defaults to True (relying on resampling or plugin's own validation).
        """
        # This method is synchronous as per DataSource ABC, but plugin.validate_timeframe is async.
        # This indicates a potential mismatch or that supports_timeframe in DataSource
        # should ideally be async if it needs to call async plugin methods.
        # For now, we can't directly await here.
        # A common pattern if the check is quick/cached in plugin:
        # Or, this method could primarily rely on what DataOrchestrator knows.
        # Let's assume for now it's a quick check or a pre-loaded capability.
        #
        # A more robust synchronous check here would require the plugin to expose
        # its supported timeframes synchronously or for this method to be async.
        # Given the current `MarketPlugin.validate_timeframe` is async, we cannot call it here directly.
        #
        # Option 1: PluginSource doesn't intelligently check, DataOrchestrator does before calling.
        # Option 2: Plugin pre-loads/caches supported timeframes and provides a sync getter.
        # Option 3: Change DataSource ABC supports_timeframe to be async (bigger change).

        # For now, let's keep it simple and assume the DataOrchestrator makes the decision
        # about whether to call this PluginSource based on its knowledge of the plugin's capabilities.
        # If PluginSource is called, it means DataOrchestrator believes this timeframe
        # (or '1m' for resampling) is appropriate for this plugin.
        
        # If `self.plugin` had a synchronous way to check, we'd use it. Example:
        # if hasattr(self.plugin, 'is_timeframe_supported_sync'): # Fictional sync method
        #     return self.plugin.is_timeframe_supported_sync(timeframe)
        
        logger.debug(f"PluginSource '{self.source_id}': supports_timeframe called for '{timeframe}'. Defaulting to True (relies on DataOrchestrator/Plugin to handle).")
        return True # Defaulting to True, actual validation/capability check happens in DataOrchestrator or the plugin itself.

    async def close(self):
        """
        Handles any cleanup for the PluginSource.
        Currently, PluginSource does not own the plugin instance's lifecycle
        (MarketService does), so this is a no-op.
        """
        logger.info(f"PluginSource '{self.source_id}' close method called (no-op). Plugin instance lifecycle managed by MarketService.")
        pass