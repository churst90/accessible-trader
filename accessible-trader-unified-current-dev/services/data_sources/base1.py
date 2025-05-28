# services/data_sources/base.py

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class DataSource(ABC):
    """
    Abstract base class for OHLCV data sources.

    Subclasses implement specific data retrieval logic (e.g., database aggregates, cache, plugins).
    Used by DataOrchestrator to fetch data in a chain of responsibility pattern.
    """

    @abstractmethod
    async def fetch_ohlcv(
        self,
        timeframe: str,
        since: Optional[int],
        before: Optional[int],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLCV bars for the given timeframe and time range.

        Args:
            timeframe (str): The timeframe string (e.g., "1m", "5m").
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
            Exception: If the fetch operation fails (handled by DataOrchestrator).
        """
        pass

    def supports_timeframe(self, timeframe: str) -> bool:
        """
        Check if the source supports the given timeframe.

        Args:
            timeframe (str): The timeframe string (e.g., "1m", "5m").

        Returns:
            bool: True if the timeframe is supported, False otherwise.
        """
        return True