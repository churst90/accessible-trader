# services/data_sources/aggregate_source.py

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from utils.db_utils import DatabaseError, fetch_query # Assuming fetch_query is in db_utils

from .base import DataSource

logger = logging.getLogger("AggregateSource")


class AggregateSource(DataSource):
    """
    DataSource for fetching OHLCV bars from TimescaleDB continuous aggregate views.

    This source queries pre-configured aggregate views (e.g., `ohlcv_5min`, `ohlcv_1h`)
    for non-1m timeframes. It retrieves view configurations from the `preaggregation_configs`
    database table. This source is typically used to serve historical data faster than
    recalculating it from raw 1-minute data.

    Attributes:
        market (str): The market identifier (e.g., "crypto", "stocks").
        provider (str): The provider identifier (e.g., "binance", "alpaca"). This should be
                        the `effective_provider_for_plugin` from MarketService.
        symbol (str): The trading pair symbol (e.g., "BTC/USD").
        _preagg_views_config_cache (Optional[Dict[str, Dict[str, Any]]]):
            Cached mapping of standardized timeframes to their full configuration
            (including view_name, base_timeframe, bucket_interval).
    """

    _global_preagg_views_config_cache: Optional[Dict[str, Dict[str, Any]]] = None
    _cache_lock = asyncio.Lock() # Lock for populating the global cache

    def __init__(self, market: str, provider: str, symbol: str):
        """
        Initialize the AggregateSource.

        Args:
            market (str): The market identifier.
            provider (str): The effective provider identifier.
            symbol (str): The trading pair symbol.

        Raises:
            ValueError: If market, provider, or symbol are invalid.
        """
        if not all([market, provider, symbol]):
            raise ValueError("AggregateSource: market, provider, and symbol must be non-empty.")

        self.market = market
        self.provider = provider # This should be the effective provider for keys/logging
        self.symbol = symbol
        logger.debug(f"AggregateSource initialized for {market}/{provider}/{symbol}.")

    def supports_timeframe(self, timeframe: str) -> bool:
        """
        Checks if a pre-aggregated view likely exists for the given timeframe.
        This source explicitly handles non-1m timeframes via aggregates.
        1m data is typically handled by other sources (CacheSource, PluginSource from raw data).
        """
        is_supported = timeframe != "1m"
        logger.debug(f"AggregateSource: Timeframe '{timeframe}' is supported for aggregates: {is_supported}.")
        return is_supported

    async def _load_preagg_configs_globally(self) -> Dict[str, Dict[str, Any]]:
        """
        Loads and caches pre-aggregation configurations globally from the database.
        This method is responsible for populating `_global_preagg_views_config_cache`.
        It queries the `preaggregation_configs` table.
        """
        async with AggregateSource._cache_lock: # Ensure only one coroutine loads it
            if AggregateSource._global_preagg_views_config_cache is not None:
                logger.debug("AggregateSource: Returning globally cached pre-aggregation configs.")
                return AggregateSource._global_preagg_views_config_cache

            logger.info("AggregateSource: Loading pre-aggregation view configurations globally from database...")
            temp_cache: Dict[str, Dict[str, Any]] = {}
            try:
                rows = await fetch_query(
                    "SELECT view_name, target_timeframe, base_timeframe, bucket_interval "
                    "FROM public.preaggregation_configs WHERE is_active = TRUE"
                )
                for row in rows:
                    config = dict(row) # Convert asyncpg.Record to dict
                    target_tf = config.get("target_timeframe")
                    if target_tf:
                        temp_cache[target_tf] = config
                        logger.debug(f"AggregateSource: Cached pre-aggregation config for timeframe '{target_tf}': {config}")
                    else:
                        logger.warning(f"AggregateSource: Skipping pre-aggregation config with missing target_timeframe: {config}")
                
                AggregateSource._global_preagg_views_config_cache = temp_cache
                logger.info(f"AggregateSource: Loaded {len(temp_cache)} active pre-aggregation configs globally.")
            except DatabaseError as e:
                logger.error(f"AggregateSource: DatabaseError fetching pre-aggregation configs: {e}", exc_info=True)
                AggregateSource._global_preagg_views_config_cache = {} # Set empty on error to avoid constant retries
                raise
            except Exception as e:
                logger.error(f"AggregateSource: Unexpected error loading pre-aggregation configs: {e}", exc_info=True)
                AggregateSource._global_preagg_views_config_cache = {}
                raise DatabaseError(f"Failed to load pre-aggregation configs: {e}") from e
            
            return AggregateSource._global_preagg_views_config_cache

    async def fetch_ohlcv(
        self,
        timeframe: str,
        since: Optional[int],
        before: Optional[int],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars from a dynamically determined TimescaleDB continuous aggregate view.
        """
        request_start_time = time.time()
        logger.debug(
            f"AggregateSource: Fetching for {self.provider}/{self.symbol}/{timeframe} "
            f"(Since: {since}, Before: {before}, Limit: {limit})"
        )

        if not self.supports_timeframe(timeframe):
            logger.debug(f"AggregateSource: Timeframe '{timeframe}' not supported by this source. Returning empty list.")
            return []

        # Load available pre-aggregate view configurations (globally cached)
        all_preagg_configs = await self._load_preagg_configs_globally()
        view_config = all_preagg_configs.get(timeframe)

        if not view_config or not view_config.get("view_name"):
            logger.info(f"AggregateSource: No active pre-aggregation config found for timeframe '{timeframe}'.")
            return []
        
        view_name = view_config["view_name"]

        # Build the SQL query
        query_clauses = ["market = $1", "provider = $2", "symbol = $3"]
        query_params: List[Any] = [self.market, self.provider, self.symbol]
        param_idx = 4 # Start parameter index for dynamic clauses

        if since is not None:
            query_clauses.append(f"bucketed_time >= ${param_idx}")
            query_params.append(datetime.fromtimestamp(since / 1000.0, tz=timezone.utc))
            param_idx += 1
        if before is not None:
            query_clauses.append(f"bucketed_time < ${param_idx}")
            query_params.append(datetime.fromtimestamp(before / 1000.0, tz=timezone.utc))
            param_idx += 1

        # Construct the SQL query string safely. view_name comes from a trusted DB config.
        # The column `bucketed_time` is assumed from your TimescaleDB continuous aggregate setup.
        sql_query_str = (
            f"SELECT (EXTRACT(EPOCH FROM bucketed_time) * 1000)::BIGINT AS timestamp, "
            f"open, high, low, close, volume "
            f"FROM public.\"{view_name}\" " # Ensure view_name is quoted if it contains special chars
            f"WHERE {' AND '.join(query_clauses)} "
            f"ORDER BY bucketed_time ASC " # Fetch oldest first
        )
        if limit > 0:
            sql_query_str += f"LIMIT ${param_idx}"
            query_params.append(limit)

        logger.debug(f"AggregateSource: Executing query on '{view_name}': {sql_query_str} with params: {query_params}")

        try:
            db_rows = await fetch_query(sql_query_str, *query_params)
            
            fetched_bars: List[Dict[str, Any]] = []
            for row in db_rows:
                try:
                    fetched_bars.append({
                        "timestamp": int(row["timestamp"]), # Already converted to ms epoch
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume"]),
                    })
                except (ValueError, TypeError, KeyError) as e_row:
                    logger.warning(f"AggregateSource: Skipping malformed row from view '{view_name}': {row}. Error: {e_row}")
            
            duration = time.time() - request_start_time
            logger.info(
                f"AggregateSource: Fetched {len(fetched_bars)} bars from aggregate view '{view_name}' "
                f"for {self.symbol}/{timeframe} in {duration:.3f}s."
            )
            return fetched_bars
        except DatabaseError as e_db:
            logger.error(f"AggregateSource: DB error fetching from '{view_name}' for {self.symbol}: {e_db}", exc_info=True)
            raise # Re-raise DatabaseError to be handled by DataOrchestrator/MarketService
        except Exception as e_unexpected:
            logger.error(f"AggregateSource: Unexpected error fetching from '{view_name}' for {self.symbol}: {e_unexpected}", exc_info=True)
            raise DatabaseError(f"Unexpected error fetching from aggregate '{view_name}': {e_unexpected}") from e_unexpected