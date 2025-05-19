# services/data_orchestrator.py

import logging
import time
from typing import Dict, List, Optional, Any

from quart import current_app
from prometheus_client import Counter, Histogram, REGISTRY  # Added REGISTRY
from utils.timeframes import UNIT_MS

from .backfill_manager import BackfillManager
from .data_sources.base import DataSource

logger = logging.getLogger("DataOrchestrator")

# Optional Prometheus metrics with duplicate prevention
try:
    if "data_orchestrator_fetch_latency" not in [m.name for m in REGISTRY._get_names()]:
        FETCH_LATENCY = Histogram(
            "data_orchestrator_fetch_latency", "Fetch latency by source", ["source"]
        )
    else:
        FETCH_LATENCY = REGISTRY._names_to_collectors["data_orchestrator_fetch_latency"]

    if "data_orchestrator_source_usage" not in [m.name for m in REGISTRY._get_names()]:
        SOURCE_USAGE = Counter(
            "data_orchestrator_source_usage", "Data source usage count", ["source"]
        )
    else:
        SOURCE_USAGE = REGISTRY._names_to_collectors["data_orchestrator_source_usage"]
except (ImportError, Exception) as e:
    logger.warning(f"Failed to initialize Prometheus metrics: {e}")
    FETCH_LATENCY = None
    SOURCE_USAGE = None


class DataOrchestrator:
    """
    Coordinates OHLCV data retrieval from multiple sources and manages historical backfills.

    Uses a chain of DataSource objects to fetch data in priority order (e.g., aggregates, cache,
    plugin). Applies time range and limit filters to the results. Delegates backfill operations to
    BackfillManager.

    Attributes:
        market (str): The market identifier (e.g., "crypto", "stocks").
        provider (str): The provider identifier (e.g., "binance", "alpaca").
        symbol (str): The trading pair symbol (e.g., "BTC/USD").
        sources (List[DataSource]): Ordered list of data sources to query.
        backfill_manager (BackfillManager): Manager for historical backfills.
        default_chart_points_api (int): Default number of bars to return if limit is not specified.
    """

    def __init__(
        self,
        market: str,
        provider: str,
        symbol: Optional[str],
        sources: List[DataSource],
        backfill_manager: BackfillManager,
    ):
        """
        Initialize the DataOrchestrator with market, provider, symbol, and data sources.

        Args:
            market (str): The market identifier.
            provider (str): The provider identifier.
            symbol (Optional[str]): The trading pair symbol (can be set later).
            sources (List[DataSource]): Ordered list of data sources.
            backfill_manager (BackfillManager): Manager for historical backfills.

        Raises:
            ValueError: If market, provider, or sources are invalid.
        """
        if not market or not provider:
            raise ValueError("market and provider must be non-empty strings")
        if not sources:
            raise ValueError("At least one data source must be provided")

        self.market = market
        self.provider = provider
        self.symbol = symbol or ""
        self.sources = sources
        self.backfill_manager = backfill_manager
        self.default_chart_points_api = int(
            current_app.config.get("DEFAULT_CHART_POINTS_API", 200)
        )

    async def fetch_ohlcv(
        self,
        timeframe: str,
        since: Optional[int] = None,
        before: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars from configured data sources, applying time range and limit filters.

        Queries sources in order until sufficient bars are collected or all sources are exhausted.
        Returns bars sorted by timestamp (oldest first).

        Args:
            timeframe (str): The timeframe string (e.g., "1m", "5m").
            since (Optional[int]): Start timestamp in milliseconds (inclusive).
            before (Optional[int]): End timestamp in milliseconds (exclusive).
            limit (Optional[int]): Maximum number of bars to return.

        Returns:
            List[Dict[str, Any]]: List of OHLCV bars, each with keys:
                - timestamp (int): Milliseconds since epoch.
                - open (float): Opening price.
                - high (float): Highest price.
                - low (float): Lowest price.
                - close (float): Closing price.
                - volume (float): Trading volume.

        Raises:
            ValueError: If symbol is not set, timeframe is invalid, or timestamps are negative.
        """
        if not self.symbol:
            raise ValueError("Symbol must be set before fetching OHLCV")
        if not timeframe:
            raise ValueError("Timeframe must be a non-empty string")
        if since is not None and since < 0:
            raise ValueError("since timestamp must be non-negative")
        if before is not None and before < 0:
            raise ValueError("before timestamp must be non-negative")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")

        start_time = time.time()
        target_bars = limit or self.default_chart_points_api
        now_ms = int(time.time() * 1000)
        actual_before_exclusive = before or now_ms
        all_bars: List[Dict[str, Any]] = []
        source_description: List[str] = []

        for source in self.sources:
            if not source.supports_timeframe(timeframe):
                continue
            # Set the correct symbol on the source instance for this request
            source.symbol = self.symbol
            try:
                bars = await source.fetch_ohlcv(
                    timeframe, since, actual_before_exclusive, target_bars
                )
                if bars:
                    all_bars.extend(bars)
                    source_name = source.__class__.__name__
                    source_description.append(source_name)
                    if SOURCE_USAGE:
                        SOURCE_USAGE.labels(source=source_name).inc()
                    if FETCH_LATENCY:
                        FETCH_LATENCY.labels(source=source_name).observe(time.time() - start_time)
                    # Stop if we have enough bars for a fresh load (since is None)
                    if len(all_bars) >= target_bars and since is None:
                        break
            except Exception as e:
                logger.warning(f"Source {source.__class__.__name__} failed: {e}", exc_info=True)

        # Merge, filter, and sort
        merged_bars = self._merge_and_sort_bars(all_bars)
        filtered_bars = self._apply_filters(
            merged_bars, since, actual_before_exclusive, target_bars
        )

        logger.info(
            f"DataOrchestrator ({self.symbol}/{timeframe}): "
            f"Source={'|'.join(source_description) or 'NoData'}, "
            f"Bars={len(filtered_bars)}, "
            f"Range=[{since if since else 'Min'}, {before if before else 'Now'}]"
        )
        return filtered_bars

    async def trigger_historical_backfill_if_needed(self, symbol: str, timeframe: str) -> None:
        """
        Trigger a historical backfill if a data gap is detected.

        Args:
            symbol (str): The trading pair symbol.
            timeframe (str): The timeframe string (ignored for backfill, which uses 1m).

        Raises:
            ValueError: If symbol or timeframe is invalid.
        """
        if not symbol:
            raise ValueError("Symbol must be non-empty")
        if not timeframe:
            raise ValueError("Timeframe must be non-empty")

        self.backfill_manager.symbol = symbol
        await self.backfill_manager.trigger_historical_backfill_if_needed(timeframe)

    def _merge_and_sort_bars(self, bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Merge and sort bars by timestamp, deduplicating by timestamp.

        Args:
            bars (List[Dict[str, Any]]): List of OHLCV bars.

        Returns:
            List[Dict[str, Any]]: Deduplicated and sorted list of bars.
        """
        merged_map = {
            bar["timestamp"]: bar for bar in bars if "timestamp" in bar
        }
        sorted_bars = sorted(merged_map.values(), key=lambda b: b["timestamp"])
        logger.debug(f"Merged and sorted {len(sorted_bars)} bars")
        return sorted_bars

    def _apply_filters(
        self,
        bars: List[Dict[str, Any]],
        since_ms: Optional[int],
        before_ms: int,
        target_bars: int,
    ) -> List[Dict[str, Any]]:
        """
        Apply time range and limit filters to the bars.

        Args:
            bars (List[Dict[str, Any]]): List of OHLCV bars.
            since_ms (Optional[int]): Start timestamp in milliseconds (inclusive).
            before_ms (int): End timestamp in milliseconds (exclusive).
            target_bars (int): Maximum number of bars to return.

        Returns:
            List[Dict[str, Any]]: Filtered list of bars.
        """
        filtered = bars
        if since_ms is not None:
            filtered = [b for b in filtered if b["timestamp"] >= since_ms]
        if before_ms is not None:
            filtered = [b for b in filtered if b["timestamp"] < before_ms]
        if len(filtered) > target_bars:
            filtered = filtered[-target_bars:] if since_ms is None else filtered[:target_bars]
        logger.debug(f"Applied filters: {len(filtered)} bars remain")
        return filtered