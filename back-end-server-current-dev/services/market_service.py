# services/market_service.py

import asyncio
import logging
import time # Keep time if used for latency metrics, else can remove
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from quart import current_app

from plugins import PluginLoader
from plugins.base import MarketPlugin, PluginError
from utils.timeframes import UNIT_MS # Keep if fetch_latest_bar uses it
from utils.db_utils import insert_ohlcv_to_db, DatabaseError

# Import NEW components
from .data_orchestrator import DataOrchestrator
from .backfill_manager import BackfillManager
from .cache_manager import Cache, RedisCache # Cache (ABC) and RedisCache (Implementation)
from .resampler import Resampler
from .data_sources.base import DataSource # Base for DataSources
from .data_sources.aggregate_source import AggregateSource
from .data_sources.cache_source import CacheSource
from .data_sources.plugin_source import PluginSource
# from redis.asyncio.exceptions import RedisError # Optional for more specific Redis error handling

logger = logging.getLogger("MarketService")

class MarketService:
    """
    Facade for accessing market data using the new DataOrchestrator and DataSource pattern.

    Initializes and coordinates plugins, caching, resampler, backfill manager,
    the DataOrchestrator, and its underlying DataSources.
    Formats data for API responses (e.g., for Highcharts).
    """

    def __init__(self, market: str, provider: str):
        """
        Initializes MarketService, setting up the data pipeline.

        Args:
            market: The market identifier (e.g., "crypto").
            provider: The provider identifier (e.g., "binance").

        Raises:
            ValueError: If essential components like plugins or managers fail to initialize.
        """
        self.market = market
        self.provider = provider
        self.plugin_key = "crypto" if market == "crypto" else provider
        self._app_config = current_app.config
        
        self.plugin: MarketPlugin
        self.redis_cache_instance: Optional[Cache] = None
        self.resampler_instance: Resampler
        self.backfill_manager: BackfillManager
        self.orchestrator: DataOrchestrator

        # 1. Load Plugin Instance
        try:
            plugin_instance = PluginLoader.load_plugin(self.plugin_key)
            if self.plugin_key != "crypto" and market not in getattr(plugin_instance, "supported_markets", []):
                raise ValueError(f"Plugin '{self.plugin_key}' does not support market '{market}'")
            self.plugin = plugin_instance
            logger.info(f"MarketService: Loaded plugin '{self.plugin_key}' for {market}/{provider}")
        except PluginError as e_plug:
            logger.critical(f"MarketService: PluginError loading plugin '{self.plugin_key}': {e_plug}", exc_info=True)
            raise ValueError(f"Market plugin '{self.plugin_key}' unavailable: {e_plug}") from e_plug
        except Exception as e_init:
            logger.critical(f"MarketService: Unexpected error initializing plugin '{self.plugin_key}': {e_init}", exc_info=True)
            raise ValueError(f"Failed to initialize market plugin '{self.plugin_key}': {e_init}") from e_init

        # 2. Initialize Cache (RedisCache)
        raw_redis_client_wrapper = self._app_config.get("CACHE") # This is utils.cache.Cache
        if raw_redis_client_wrapper and hasattr(raw_redis_client_wrapper, 'redis') and raw_redis_client_wrapper.redis:
            try:
                self.redis_cache_instance = RedisCache(redis_client=raw_redis_client_wrapper.redis)
                logger.info("MarketService: RedisCache initialized.")
            except ValueError as ve_rc:
                logger.error(f"MarketService: Failed to initialize RedisCache: {ve_rc}", exc_info=True)
            except Exception as e_rc_init:
                logger.error(f"MarketService: Unexpected error initializing RedisCache: {e_rc_init}", exc_info=True)
        else:
            logger.warning("MarketService: No base Redis client found. RedisCache not initialized.")
        
        # 3. Initialize Resampler
        self.resampler_instance = Resampler()

        # 4. Initialize BackfillManager
        try:
            self.backfill_manager = BackfillManager(
                market=self.market,
                provider=self.provider,
                symbol=None, # Pass None or "", DataOrchestrator will set it specifically
                plugin=self.plugin,
                cache=self.redis_cache_instance
            )
            logger.info("MarketService: BackfillManager initialized.")
        except ValueError as ve_bm: # Catch init errors from BackfillManager
            logger.critical(f"MarketService: Failed to initialize BackfillManager: {ve_bm}", exc_info=True)
            raise ValueError(f"BackfillManager initialization error: {ve_bm}") from ve_bm
        except Exception as e_bm_gen:
             logger.critical(f"MarketService: Unexpected error initializing BackfillManager: {e_bm_gen}", exc_info=True)
             raise RuntimeError(f"BackfillManager fatal init error: {e_bm_gen}") from e_bm_gen

        # 5. Create DataSources List (Order defines fetch priority)
        # These sources are initialized with a general context; DataOrchestrator will set the specific symbol.
        data_sources_list: List[DataSource] = [
            AggregateSource(market=self.market, provider=self.provider, symbol=""), # Symbol placeholder
            CacheSource(
                market=self.market, provider=self.provider, symbol="", # Symbol placeholder
                cache=self.redis_cache_instance, 
                resampler=self.resampler_instance
            ),
            PluginSource(
                market=self.market, provider=self.provider, symbol="", # Symbol placeholder
                plugin=self.plugin, 
                cache=self.redis_cache_instance, 
                resampler=self.resampler_instance
            )
        ]
        if not self.redis_cache_instance: # If no cache, remove CacheSource or don't add it
            data_sources_list = [s for s in data_sources_list if not isinstance(s, CacheSource)]
            logger.warning("MarketService: CacheSource not included due to unavailable RedisCache.")

        # 6. Initialize new DataOrchestrator
        try:
            self.orchestrator = DataOrchestrator(
                market=self.market,
                provider=self.provider,
                symbol=None,  # Will be set per API call to fetch_ohlcv
                sources=data_sources_list,
                backfill_manager=self.backfill_manager
            )
            logger.info("MarketService: DataOrchestrator initialized.")
        except ValueError as ve_do: # Catch init errors from DataOrchestrator
            logger.critical(f"MarketService: Failed to initialize DataOrchestrator: {ve_do}", exc_info=True)
            raise ValueError(f"DataOrchestrator initialization error: {ve_do}") from ve_do
        except Exception as e_do_gen:
            logger.critical(f"MarketService: Unexpected error initializing DataOrchestrator: {e_do_gen}", exc_info=True)
            raise RuntimeError(f"DataOrchestrator fatal init error: {e_do_gen}") from e_do_gen


    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None,
        before: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, List[List[Any]]]:
        """
        Retrieves and formats OHLCV data for Highcharts.
        Delegates to DataOrchestrator.
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty for fetch_ohlcv.")
        
        # Set the symbol for the current operation on orchestrator and its components
        self.orchestrator.symbol = symbol
        # The new DataOrchestrator's fetch_ohlcv takes symbol as an argument.
        # Individual data sources get their symbol from the orchestrator before their fetch_ohlcv is called.

        logger.debug(f"MarketService: Delegating fetch_ohlcv for {self.market}/{self.provider}/{symbol} to DataOrchestrator.")
        
        try:
            # Pass symbol to DataOrchestrator's fetch_ohlcv method
            bars = await self.orchestrator.fetch_ohlcv(timeframe, since, before, limit)
        except ValueError: # Propagate ValueErrors (e.g. bad timeframe, bad symbol)
            raise
        except Exception as e_orch_fetch:
            logger.error(f"MarketService: Unhandled error from DataOrchestrator for {symbol}: {e_orch_fetch}", exc_info=True)
            bars = [] # Default to empty bars on unhandled orchestrator error
            # Or consider re-raising a generic "data unavailable" error
            # raise RuntimeError(f"Data fetch failed for {symbol}") from e_orch_fetch

        ohlc_data: List[List[Any]] = []
        volume_data: List[List[Any]] = []
        for bar in bars: # bars should be an empty list if an error occurred and was handled by returning []
            ts = bar.get("timestamp")
            if ts is None:
                logger.warning(f"MarketService: Bar missing timestamp for {symbol}: {bar}")
                continue
            try:
                ohlc_data.append([
                    ts, float(bar["open"]), float(bar["high"]),
                    float(bar["low"]), float(bar["close"]),
                ])
                volume_data.append([ts, float(bar.get("volume", 0.0))])
            except (TypeError, ValueError, KeyError) as e_format:
                logger.warning(f"MarketService: Skipping malformed bar for {symbol}: {bar}. Error: {e_format}")
        
        logger.info(f"MarketService: Prepared {len(ohlc_data)} bars for Highcharts for {symbol}/{timeframe}.")
        return {"ohlc": ohlc_data, "volume": volume_data}

    async def fetch_latest_bar(
        self,
        symbol: str,
        timeframe: str, # Usually "1m" for this specific method's intent
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches the single most recent 1-minute OHLCV bar via the plugin.
        This version does NOT use its own distinct caching layer; caching for 1m data
        is handled by CacheSource if it's part of the DataOrchestrator's sources.
        For a truly "latest tick" behavior, a streaming source or more specialized caching might be needed.
        """
        if not symbol: raise ValueError("Symbol must be provided")
        logger.debug(f"MarketService: Fetching latest bar for {symbol} (target timeframe {timeframe}, plugin uses 1m).")
        try:
            # Directly call plugin; DataOrchestrator is for series.
            latest_bar = await self.plugin.fetch_latest_ohlcv(
                provider=self.provider, symbol=symbol, timeframe="1m"
            )
            if latest_bar and isinstance(latest_bar.get("timestamp"), int):
                # Asynchronously store to DB (and CacheSource will pick it up if it queries DB or plugin stores to cache)
                asyncio.create_task(
                    insert_ohlcv_to_db(self.market, self.provider, symbol, "1m", [latest_bar])
                )
                # If CacheSource needs explicit update, it's more complex here, as MarketService
                # doesn't directly manage the CacheSource's internal logic.
                # The PluginSource, if used by DataOrchestrator, might also cache it.
                if self.redis_cache_instance:
                    # Example of updating generic 1m cache if desired for this specific latest bar
                     try:
                         await self.redis_cache_instance.store_1m_bars(self.market, self.provider, symbol, [latest_bar])
                     except Exception as e_cache:
                         logger.warning(f"Failed to store latest_bar in cache for {symbol}: {e_cache}")

                return latest_bar
            else:
                logger.warning(f"MarketService: Plugin returned invalid latest_bar for {symbol}: {latest_bar}")
                return None
        except PluginError as e_plug:
            logger.error(f"MarketService: PluginError fetching latest bar for {symbol}: {e_plug}", exc_info=True)
            return None
        except Exception as e_gen:
            logger.error(f"MarketService: Unexpected error fetching latest bar for {symbol}: {e_gen}", exc_info=True)
            return None

    async def get_symbols(self) -> List[str]:
        """Retrieves tradable symbols from the configured plugin."""
        logger.debug(f"MarketService: Getting symbols for {self.market}/{self.provider} via plugin '{self.plugin_key}'.")
        try:
            return await self.plugin.get_symbols(provider=self.provider)
        except PluginError: # Let blueprint handle PluginError specifically
            raise
        except Exception as e:
            logger.error(f"MarketService: Unexpected error in get_symbols for {self.market}/{self.provider}: {e}", exc_info=True)
            raise RuntimeError(f"Unexpected error fetching symbols: {e}") from e

    async def trigger_historical_backfill_if_needed(self, symbol: str, timeframe: str):
        """Delegates to DataOrchestrator to trigger backfill."""
        if not symbol: raise ValueError("Symbol is required for backfill trigger.")
        logger.info(f"MarketService: Relaying backfill trigger for {symbol} (TF context: {timeframe}) to DataOrchestrator.")
        self.orchestrator.symbol = symbol # Ensure orchestrator has current symbol
        self.backfill_manager.symbol = symbol # Ensure backfill manager also has current symbol
        await self.orchestrator.trigger_historical_backfill_if_needed(symbol, timeframe)

    async def save_recent_bars_to_db_and_cache(
        self,
        symbol: str,
        timeframe: str,
        bars: List[Dict[str, Any]],
    ):
        """Saves recent bars to DB and attempts to store in 1m cache if applicable."""
        if not all([symbol, timeframe, bars]):
            logger.warning("MarketService: Insufficient data for save_recent_bars_to_db_and_cache.")
            return

        logger.info(f"MarketService: Saving {len(bars)} bars for {symbol}/{timeframe} to DB/Cache.")
        try:
            asyncio.create_task(
                insert_ohlcv_to_db(self.market, self.provider, symbol, timeframe, bars)
            )
        except DatabaseError as dbe: # create_task might not let this be caught easily
            logger.error(f"MarketService: DB error creating task for DB insert: {dbe}", exc_info=True)
        except Exception as e:
            logger.error(f"MarketService: Error creating DB insert task: {e}", exc_info=True)

        if self.redis_cache_instance and timeframe == "1m": # Only cache 1m bars this way
            try:
                await self.redis_cache_instance.store_1m_bars(self.market, self.provider, symbol, bars)
            except Exception as e_cache:
                logger.error(f"MarketService: Error storing bars in RedisCache: {e_cache}", exc_info=True)