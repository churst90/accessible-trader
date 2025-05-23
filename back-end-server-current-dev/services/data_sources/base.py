# services/data_sources/base.py

import logging # Added logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

from plugins.base import OHLCVBar # For type hinting consistency

logger = logging.getLogger(__name__)

# --- Custom DataSource Exceptions ---

class DataSourceError(Exception):
    """Base exception for all data source-related errors."""
    def __init__(self, message: str, source_id: Optional[str] = None, original_exception: Optional[Exception] = None):
        self.source_id = source_id
        self.original_exception = original_exception
        full_message = f"DataSource error"
        if source_id:
            full_message += f" from source '{source_id}'"
        full_message += f": {message}"
        if original_exception:
            orig_exc_str = str(original_exception)
            if len(orig_exc_str) > 150:
                orig_exc_str = orig_exc_str[:150] + "..."
            full_message += f" (Original: {type(original_exception).__name__}: {orig_exc_str})"
        super().__init__(full_message)

class DataSourceFeatureNotSupportedError(DataSourceError):
    """Exception for when a data source does not support a requested feature."""
    def __init__(self, source_id: str, feature_name: str, message: Optional[str] = None):
        self.feature_name = feature_name
        super().__init__(
            message=message or f"Feature '{feature_name}' not supported by this data source.",
            source_id=source_id
        )

class AuthenticationDataSourceError(DataSourceError):
    """Exception for authentication errors with a data source (e.g., if it wraps a plugin)."""
    def __init__(self, source_id: str, message: str = "Authentication failed.", original_exception: Optional[Exception] = None):
        super().__init__(message=message, source_id=source_id, original_exception=original_exception)

class DataSourceNetworkError(DataSourceError):
    """Exception for network-related errors when a data source interacts with an external service."""
    def __init__(self, source_id: str, message: str = "Network error.", original_exception: Optional[Exception] = None):
        super().__init__(message=message, source_id=source_id, original_exception=original_exception)


# --- Abstract Base Class for DataSources ---

class DataSource(ABC):
    """
    Abstract base class for OHLCV data sources.

    Subclasses implement specific data retrieval logic (e.g., from database aggregates,
    cache, or plugins). Instances are used by the DataOrchestrator to fetch data in a
    chain-of-responsibility pattern. Each DataSource instance should have a unique `source_id`.
    """

    def __init__(self, source_id: str):
        """
        Initializes the DataSource.

        Args:
            source_id (str): A unique identifier for the data source instance
                             (e.g., "db:crypto:binance:BTC/USD", "cache:generic", "plugin:alpaca:AAPL").
        """
        if not source_id:
            raise ValueError("DataSource instances must be initialized with a non-empty source_id.")
        self.source_id: str = source_id
        logger.debug(f"DataSource '{self.source_id}' initialized.")

    @abstractmethod
    async def fetch_ohlcv(
        self,
        timeframe: str,
        since: Optional[int],
        before: Optional[int], # 'before' is exclusive for the range end
        limit: int,
        # No market, provider, symbol here - instance is already specific or methods handle it.
    ) -> List[OHLCVBar]: # Changed return type to List[OHLCVBar]
        """
        Fetch OHLCV bars for the configured asset of this DataSource instance,
        within the given timeframe and time range.

        Args:
            timeframe (str): The timeframe string (e.g., "1m", "5m", "1H").
            since (Optional[int]): Start timestamp in milliseconds (inclusive, UTC).
            before (Optional[int]): End timestamp in milliseconds (exclusive, UTC).
                                   Used to define the upper bound of the query range.
            limit (int): Maximum number of bars to return. Note that a source might
                         return fewer bars if the requested range is small or data is sparse.

        Returns:
            List[OHLCVBar]: A list of OHLCV bars, ideally sorted by timestamp ascending.
                            Returns an empty list if no data is found.

        Raises:
            DataSourceError (and its subclasses): If the fetch operation fails.
            ValueError: For invalid parameters if not caught internally.
        """
        pass

    def supports_timeframe(self, timeframe: str) -> bool:
        """
        Indicates if the data source generally supports fetching data for the given timeframe.
        This might mean native support or that it provides base data (e.g., 1m)
        from which the target timeframe can be derived by resampling.

        Args:
            timeframe (str): The timeframe string (e.g., "1m", "5m").

        Returns:
            bool: True if the timeframe is considered supported by this source, False otherwise.
                  Default implementation returns True, assuming the source is versatile or provides
                  base data for resampling. Subclasses should override for more specific checks.
        """
        logger.debug(f"DataSource '{self.source_id}': supports_timeframe check for '{timeframe}' (defaulting to True).")
        return True
    
    async def close(self) -> None:
        """
        Perform any cleanup for the DataSource instance if needed.
        Default implementation is a no-op. Subclasses can override if they
        manage resources that need explicit closing (though often dependencies
        like plugin instances are managed externally).
        """
        logger.debug(f"DataSource '{self.source_id}': close() called (default no-op).")
        pass