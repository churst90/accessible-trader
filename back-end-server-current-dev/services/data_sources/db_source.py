# services/data_sources/db_source.py

import logging
from typing import List, Optional, Dict, Any

# Assuming db_utils are in a reachable 'utils' package
from utils.db_utils import (
    fetch_ohlcv_from_db,
    insert_ohlcv_to_db,
    DatabaseError # Make sure DatabaseError is defined in db_utils or imported there
)
from plugins.base import OHLCVBar # For type hinting
from .base import DataSource # For inheritance

logger = logging.getLogger(__name__)

class DbSource(DataSource):
    """
    DataSource for interacting with the primary OHLCV database table.
    - This class provides methods to fetch data (though typically CacheSource handles DB reads)
      and is used by DataOrchestrator to WRITE new 1m data (from plugins) to the database.
    """

    def __init__(self, market: Optional[str] = None, provider: Optional[str] = None, symbol: Optional[str] = None, app_context=None):
        """
        Initializes the DbSource.

        If market, provider, and symbol are provided, this instance is configured for a specific
        instrument for fetching. If they are None, the instance is generic, and these
        parameters must be provided to fetch/store methods. DataOrchestrator typically
        uses a generic instance for writes.

        Args:
            market (Optional[str]): Market identifier for specific instance context.
            provider (Optional[str]): Provider identifier for specific instance context.
            symbol (Optional[str]): Trading symbol for specific instance context.
            app_context: Application context (e.g., current_app), typically not needed if db_utils uses current_app.
        """
        self.market = market
        self.provider = provider
        self.symbol = symbol
        # self.app_context = app_context # Not strictly needed if db_utils uses current_app
        if market and provider and symbol:
            super().__init__(source_id=f"db:{market}:{provider}:{symbol}")
            logger.info(f"DbSource initialized for {market}/{provider}/{symbol}.")
        else:
            super().__init__(source_id="db:generic")
            logger.info("DbSource initialized as a generic DB access service.")


    async def fetch_ohlcv(self, timeframe: str,
                          since: Optional[int] = None,
                          before: Optional[int] = None, # Matches DataSource ABC 'before'
                          limit: Optional[int] = None,
                          # Allow overriding instance market/provider/symbol if they are None
                          market: Optional[str] = None,
                          provider: Optional[str] = None,
                          symbol: Optional[str] = None
                          ) -> List[Dict[str, Any]]: # ABC expects List[Dict]
        """
        Fetches OHLCV data directly from the database.
        Uses instance market/provider/symbol if set, otherwise expects them as arguments.
        """
        eff_market = market if market is not None else self.market
        eff_provider = provider if provider is not None else self.provider
        eff_symbol = symbol if symbol is not None else self.symbol

        if not all([eff_market, eff_provider, eff_symbol]):
            raise ValueError("DbSource.fetch_ohlcv: Market, provider, and symbol must be specified either at init or during call.")

        logger.debug(f"DbSource: Fetching OHLCV for {eff_market}:{eff_provider}:{eff_symbol}@{timeframe} "
                     f"(since={since}, before={before}, limit={limit})")
        try:
            # utils.db_utils.fetch_ohlcv_from_db returns List[Dict[str, Any]]
            # and expects 'before' and optional 'limit'.
            # The limit in DataSource ABC is int, db_utils takes Optional[int].
            effective_limit = limit if limit is not None else -1 # Or handle None appropriately in db_utils
            if limit is None: # fetch_ohlcv_from_db expects Optional[int]
                 pass # pass None to fetch_ohlcv_from_db
            elif limit <=0: # If limit is passed as non-positive from ABC, it might be an issue.
                 logger.warning(f"DbSource.fetch_ohlcv called with non-positive limit {limit}. Fetching all matching records.")
                 pass # Pass None to fetch_ohlcv_from_db for "no limit"

            raw_bars = await fetch_ohlcv_from_db(
                eff_market, eff_provider, eff_symbol, timeframe, since, before=before, limit=limit
            )
            return raw_bars # Already List[Dict[str, Any]]
        except DatabaseError as e:
            logger.error(f"DbSource: DatabaseError during fetch_ohlcv for {eff_market}:{eff_provider}:{eff_symbol}@{timeframe}: {e}")
            raise
        except Exception as e:
            logger.error(f"DbSource: Unexpected error during fetch_ohlcv for {eff_market}:{eff_provider}:{eff_symbol}@{timeframe}: {e}", exc_info=True)
            raise DatabaseError(f"Unexpected DB error during fetch: {e}") from e


    async def store_ohlcv_bars(self, market: str, provider: str, symbol: str,
                               timeframe: str, bars: List[OHLCVBar]):
        """
        Stores (upserts) OHLCV bars into the database.
        This is the primary method used by DataOrchestrator for this class instance.

        Args:
            market: Market identifier.
            provider: Provider identifier.
            symbol: Trading symbol.
            timeframe: Timeframe string (typically '1m' when called by DataOrchestrator).
            bars: List of OHLCVBar objects to store.
        """
        if not bars:
            logger.debug(f"DbSource: No bars to store for {market}:{provider}:{symbol}@{timeframe}.")
            return

        # Convert List[OHLCVBar] to List[Dict[str, Any]] for insert_ohlcv_to_db
        dict_bars = [dict(bar) for bar in bars]

        logger.debug(f"DbSource: Storing {len(dict_bars)} bars for {market}:{provider}:{symbol}@{timeframe}.")
        try:
            await insert_ohlcv_to_db(market, provider, symbol, timeframe, dict_bars)
            logger.info(f"DbSource: Successfully stored {len(dict_bars)} bars for {market}:{provider}:{symbol}@{timeframe}.")
        except DatabaseError as e:
            logger.error(f"DbSource: DatabaseError during store_ohlcv_bars for {market}:{provider}:{symbol}@{timeframe}: {e}")
            raise # Propagate error
        except Exception as e:
            logger.error(f"DbSource: Unexpected error during store_ohlcv_bars for {market}:{provider}:{symbol}@{timeframe}: {e}", exc_info=True)
            raise DatabaseError(f"Unexpected DB storage error: {e}") from e

    def supports_timeframe(self, timeframe: str) -> bool:
        """
        Indicates if the DbSource (raw ohlcv_data table) generally supports a timeframe.
        The underlying table can store any timeframe.
        """
        # For practical purposes, if reading directly via DbSource in the orchestrator chain,
        # it's often for '1m' data, as aggregates/cache handle others.
        # However, the table itself can store any timeframe.
        return True