# services/data_sources/aggregate_source.py

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from quart import current_app
from utils.db_utils import DatabaseError, fetch_query

from .base import DataSource

logger = logging.getLogger("AggregateSource")


class AggregateSource(DataSource):
    """
    DataSource for fetching OHLCV bars from TimescaleDB continuous aggregate views.

    Queries views like ohlcv_5min, ohlcv_1h for non-1m timeframes. Caches view names for efficiency.
    Returns empty results for 1m timeframes.

    Attributes:
        market (str): The market identifier (e.g., "crypto", "stocks").
        provider (str): The provider identifier (e.g., "binance", "alpaca").
        symbol (str): The trading pair symbol (e.g., "BTC/USD").
        _preagg_views_cache (Optional[Dict[str, str]]): Cached mapping of timeframes to view names.
    """

    def __init__(self, market: str, provider: str, symbol: str):
        """
        Initialize the AggregateSource.

        Args:
            market (str): The market identifier.
            provider (str): The provider identifier.
            symbol (str): The trading pair symbol.

        Raises:
            ValueError: If market, provider, or symbol are invalid.
        """
        if not market or not provider:
            raise ValueError("market and provider must be non-empty strings")
        self.market = market
        self.provider = provider
        self.symbol = symbol
        self._preagg_views_cache: Optional[Dict[str, str]] = None

    def supports_timeframe(self, timeframe: str) -> bool:
        """
        Check if the source supports the given timeframe.

        Only non-1m timeframes are supported, as 1m data is not stored in continuous aggregates.

        Args:
            timeframe (str): The timeframe string (e.g., "1m", "5m").

        Returns:
            bool: True for non-1m timeframes, False for 1m.
        """
        return timeframe != "1m"

    async def fetch_ohlcv(
        self,
        timeframe: str,
        since: Optional[int],
        before: Optional[int],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars from a TimescaleDB continuous aggregate view.

        Args:
            timeframe (str): The timeframe string (e.g., "5m", "1h").
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            before (Optional[int]): End timestamp in milliseconds (exclusive).
            limit (int): Maximum number of bars to return.

        Returns:
            List[Dict[str, Any]]: List of OHLCV bars, each with keys:
                - timestamp (int): Milliseconds since epoch.
                - open (float): Opening price.
                - high (float): Highest price.
                - low (float): Lowest price.
                - close (float): Closing price.
                - volume (float): Trading volume.

        Raises:
            DatabaseError: If the database query fails.
        """
        preagg_views = await self._load_preagg_views()
        view_name = preagg_views.get(timeframe)
        if not view_name:
            logger.debug(f"No continuous aggregate view found for timeframe '{timeframe}'")
            return []

        clauses = ["market=$1", "provider=$2", "symbol=$3"]
        params = [self.market, self.provider, self.symbol]
        idx = 4

        if since is not None:
            clauses.append(f"bucketed_time >= ${idx}")
            params.append(datetime.fromtimestamp(since / 1000.0, tz=timezone.utc))
            idx += 1
        if before is not None:
            clauses.append(f"bucketed_time < ${idx}")
            params.append(datetime.fromtimestamp(before / 1000.0, tz=timezone.utc))
            idx += 1

        limit_sql = f"LIMIT ${idx}" if limit > 0 else ""
        if limit > 0:
            params.append(limit)

        sql = (
            f"SELECT bucketed_time AS timestamp, open, high, low, close, volume "
            f"FROM public.\"{view_name}\" "
            f"WHERE {' AND '.join(clauses)} ORDER BY bucketed_time ASC {limit_sql}"
        )

        try:
            rows = await fetch_query(sql, *params)
            bars = [
                {
                    "timestamp": int(r["timestamp"].timestamp() * 1000),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": float(r["volume"]),
                }
                for r in rows
            ]
            logger.debug(f"Fetched {len(bars)} bars from continuous aggregate '{view_name}'")
            return bars
        except DatabaseError as e:
            logger.error(f"Error fetching CA '{view_name}': {e} | SQL: {sql} | Params: {params}", exc_info=True)
            raise

    async def _load_preagg_views(self) -> Dict[str, str]:
        """
        Load and cache TimescaleDB continuous aggregate view names.

        Returns:
            Dict[str, str]: Mapping of standardized timeframes to view names.

        Raises:
            DatabaseError: If the query fails.
        """
        if self._preagg_views_cache is not None:
            return self._preagg_views_cache

        self._preagg_views_cache = {}
        try:
            rows = await fetch_query(
                "SELECT view_name FROM timescaledb_information.continuous_aggregates "
                "WHERE view_schema = 'public' AND view_name LIKE 'ohlcv_%'"
            )
            for r in rows:
                view_name = r.get("view_name", "") if isinstance(r, dict) else r[0]
                if not isinstance(view_name, str):
                    continue
                tf_part = view_name.split("ohlcv_", 1)[1] if "ohlcv_" in view_name else view_name
                std = None
                for suffix, replacement in [
                    ("min", "m"),
                    ("hour", "h"),
                    ("day", "d"),
                    ("week", "w"),
                    ("month", "M"),
                    ("year", "y"),
                ]:
                    if tf_part.endswith(suffix):
                        std = tf_part.replace(suffix, replacement)
                        break
                if std:
                    self._preagg_views_cache[std] = view_name
            logger.debug(f"Loaded {len(self._preagg_views_cache)} continuous aggregate views")
        except DatabaseError as e:
            logger.error(f"Failed to load continuous aggregate views: {e}", exc_info=True)
            self._preagg_views_cache = {}
        return self._preagg_views_cache