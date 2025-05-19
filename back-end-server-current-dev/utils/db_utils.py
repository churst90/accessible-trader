# utils/db-utils.py

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import asyncpg
from quart import current_app

logger = logging.getLogger("DatabaseUtils")


class DatabaseError(Exception):
    """Custom exception for database-related errors."""
    pass


async def fetch_query(query: str, *params: Any) -> List[asyncpg.Record]:
    """
    Execute a SELECT-style query with positional parameters.

    Args:
        query (str): The SQL query to execute.
        *params: Variable positional parameters for the query.

    Returns:
        List[asyncpg.Record]: A list of query result records.

    Raises:
        DatabaseError: If the database connection pool is not initialized or the query fails.
    """
    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise DatabaseError("Database connection pool is not initialized")

    async with pool.acquire() as conn:
        try:
            result = await conn.fetch(query, *params)
            logger.debug(f"fetch_query: {query} | params={params}")
            return result
        except Exception as e:
            logger.error(f"Error in fetch_query: {e} | Query: {query} | Params: {params}", exc_info=True)
            raise DatabaseError(f"Query execution failed: {e}")


async def execute_query(query: str, *params: Any) -> None:
    """
    Execute an INSERT/UPDATE/DELETE-style query with positional parameters.

    Args:
        query (str): The SQL query to execute.
        *params: Variable positional parameters for the query.

    Raises:
        DatabaseError: If the database connection pool is not initialized or the query fails.
    """
    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise DatabaseError("Database connection pool is not initialized")

    async with pool.acquire() as conn:
        try:
            await conn.execute(query, *params)
            logger.debug(f"execute_query: {query} | params={params}")
        except Exception as e:
            logger.error(f"Error in execute_query: {e} | Query: {query} | Params: {params}", exc_info=True)
            raise DatabaseError(f"Query execution failed: {e}")


async def fetch_ohlcv_from_db(
    market: str,
    provider: str,
    symbol: str,
    timeframe: str,
    since: Optional[int] = None,
    before: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch OHLCV bars from the database, ordered from oldest to newest.

    Args:
        market (str): The market identifier (e.g., "crypto", "stocks").
        provider (str): The provider identifier (e.g., "binance", "alpaca").
        symbol (str): The trading pair symbol (e.g., "BTC/USD").
        timeframe (str): The timeframe string (e.g., "1m", "5m").
        since (Optional[int]): Start timestamp in milliseconds (inclusive).
        before (Optional[int]): End timestamp in milliseconds (exclusive).
        limit (Optional[int]): Maximum number of bars to return.

    Returns:
        List[Dict[str, Any]]: A list of OHLCV bars, each with keys:
            - timestamp (int): Milliseconds since epoch.
            - open (float): Opening price.
            - high (float): Highest price.
            - low (float): Lowest price.
            - close (float): Closing price.
            - volume (float): Trading volume.

    Raises:
        DatabaseError: If the query fails or the connection pool is not initialized.
        ValueError: If timestamps or limit are invalid.
    """
    if since is not None and since < 0:
        raise ValueError("since timestamp must be non-negative")
    if before is not None and before < 0:
        raise ValueError("before timestamp must be non-negative")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")

    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise DatabaseError("Database connection pool is not initialized")

    sql = (
        "SELECT timestamp, open, high, low, close, volume "
        "FROM ohlcv_data "
        "WHERE market=$1 AND provider=$2 AND symbol=$3 AND timeframe=$4"
    )
    params: List[Any] = [market, provider, symbol, timeframe]
    idx = 5

    if since is not None:
        sql += f" AND timestamp >= ${idx}"
        params.append(datetime.fromtimestamp(since / 1000.0))
        idx += 1

    if before is not None:
        sql += f" AND timestamp < ${idx}"
        params.append(datetime.fromtimestamp(before / 1000.0))
        idx += 1

    sql += " ORDER BY timestamp ASC"
    if limit is not None:
        sql += f" LIMIT ${idx}"
        params.append(limit)

    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(sql, *params)
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
            logger.debug(f"fetch_ohlcv_from_db: Fetched {len(bars)} bars | params={params}")
            return bars
        except Exception as e:
            logger.error(f"Error in fetch_ohlcv_from_db: {e} | Query: {sql} | Params: {params}", exc_info=True)
            raise DatabaseError(f"Failed to fetch OHLCV data: {e}")


async def fetch_historical_ohlcv_from_db(
    market: str,
    provider: str,
    symbol: str,
    timeframe: str,
    before: Optional[int],
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Fetch up to `limit` OHLCV bars older than `before`, ordered from oldest to newest.

    Args:
        market (str): The market identifier (e.g., "crypto", "stocks").
        provider (str): The provider identifier (e.g., "binance", "alpaca").
        symbol (str): The trading pair symbol (e.g., "BTC/USD").
        timeframe (str): The timeframe string (e.g., "1m", "5m").
        before (Optional[int]): End timestamp in milliseconds (exclusive).
        limit (int): Maximum number of bars to return (default: 100).

    Returns:
        List[Dict[str, Any]]: A list of OHLCV bars, each with keys:
            - timestamp (int): Milliseconds since epoch.
            - open (float): Opening price.
            - high (float): Highest price.
            - low (float): Lowest price.
            - close (float): Closing price.
            - volume (float): Trading volume.

    Raises:
        DatabaseError: If the query fails or the connection pool is not initialized.
        ValueError: If before or limit are invalid.
    """
    if before is None:
        return []
    if before < 0:
        raise ValueError("before timestamp must be non-negative")
    if limit <= 0:
        raise ValueError("limit must be positive")

    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise DatabaseError("Database connection pool is not initialized")

    before_dt = datetime.fromtimestamp(before / 1000.0)
    sql = (
        "SELECT timestamp, open, high, low, close, volume "
        "FROM ohlcv_data "
        "WHERE market=$1 AND provider=$2 AND symbol=$3 AND timeframe=$4 AND timestamp < $5 "
        "ORDER BY timestamp ASC "  # Changed to ASC to avoid reversal
        "LIMIT $6"
    )
    params = [market, provider, symbol, timeframe, before_dt, limit]

    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(sql, *params)
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
            logger.debug(f"fetch_historical_ohlcv_from_db: Fetched {len(bars)} bars before {before}")
            return bars
        except Exception as e:
            logger.error(f"Error in fetch_historical_ohlcv_from_db: {e} | Query: {sql} | Params: {params}", exc_info=True)
            raise DatabaseError(f"Failed to fetch historical OHLCV data: {e}")


async def insert_ohlcv_to_db(
    market: str,
    provider: str,
    symbol: str,
    timeframe: str,
    data: List[Dict[str, Any]],
) -> None:
    """
    Bulk upsert OHLCV bars into the ohlcv_data table.

    Args:
        market (str): The market identifier (e.g., "crypto", "stocks").
        provider (str): The provider identifier (e.g., "binance", "alpaca").
        symbol (str): The trading pair symbol (e.g., "BTC/USD").
        timeframe (str): The timeframe string (e.g., "1m", "5m").
        data (List[Dict[str, Any]]): List of OHLCV bars, each with keys:
            - timestamp (int): Milliseconds since epoch.
            - open (float): Opening price.
            - high (float): Highest price.
            - low (float): Lowest price.
            - close (float): Closing price.
            - volume (float): Trading volume.

    Raises:
        DatabaseError: If the query fails or the connection pool is not initialized.
        ValueError: If the data list is empty or contains invalid entries.
    """
    if not data:
        logger.debug("insert_ohlcv_to_db: No data to insert")
        return
    if not all(
        isinstance(bar.get("timestamp"), int) and
        all(isinstance(bar.get(k), (int, float)) for k in ("open", "high", "low", "close", "volume"))
        for bar in data
    ):
        raise ValueError("Invalid OHLCV data format")

    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise DatabaseError("Database connection pool is not initialized")

    sql = """
    INSERT INTO ohlcv_data
      (market, provider, symbol, timeframe, timestamp, open, high, low, close, volume)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
    ON CONFLICT (market, provider, symbol, timeframe, timestamp) DO UPDATE
      SET open = EXCLUDED.open,
          high = EXCLUDED.high,
          low = EXCLUDED.low,
          close = EXCLUDED.close,
          volume = EXCLUDED.volume
    """

    params_list = [
        (
            market,
            provider,
            symbol,
            timeframe,
            datetime.fromtimestamp(bar["timestamp"] / 1000.0),
            float(bar["open"]),
            float(bar["high"]),
            float(bar["low"]),
            float(bar["close"]),
            float(bar["volume"]),
        )
        for bar in data
    ]

    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                await conn.executemany(sql, params_list)
                logger.debug(f"insert_ohlcv_to_db: Upserted {len(params_list)} bars for {market}/{provider}/{symbol}/{timeframe}")
            except Exception as e:
                logger.error(f"Error in insert_ohlcv_to_db: {e} | Params count: {len(params_list)}", exc_info=True)
                raise DatabaseError(f"Failed to insert OHLCV data: {e}")


async def has_data_in_range(
    market: str,
    provider: str,
    symbol: str,
    timeframe: str,
    since_ms: int,
    before_ms: int,
) -> bool:
    """
    Check if any OHLCV data exists in the specified time range.

    Args:
        market (str): The market identifier (e.g., "crypto", "stocks").
        provider (str): The provider identifier (e.g., "binance", "alpaca").
        symbol (str): The trading pair symbol (e.g., "BTC/USD").
        timeframe (str): The timeframe string (e.g., "1m", "5m").
        since_ms (int): Start timestamp in milliseconds (inclusive).
        before_ms (int): End timestamp in milliseconds (exclusive).

    Returns:
        bool: True if data exists in the range, False otherwise.

    Raises:
        DatabaseError: If the query fails or the connection pool is not initialized.
        ValueError: If timestamps are invalid.
    """
    if since_ms < 0 or before_ms < 0:
        raise ValueError("Timestamps must be non-negative")
    if since_ms >= before_ms:
        raise ValueError("since_ms must be less than before_ms")

    query = (
        "SELECT 1 FROM ohlcv_data "
        "WHERE market=$1 AND provider=$2 AND symbol=$3 AND timeframe=$4 "
        "AND timestamp >= $5 AND timestamp < $6 LIMIT 1"
    )
    since_dt = datetime.fromtimestamp(since_ms / 1000.0)
    before_dt = datetime.fromtimestamp(before_ms / 1000.0)

    try:
        rows = await fetch_query(query, market, provider, symbol, timeframe, since_dt, before_dt)
        result = bool(rows)
        logger.debug(f"has_data_in_range: {'Data found' if result else 'No data'} in range [{since_ms}, {before_ms})")
        return result
    except DatabaseError as e:
        logger.error(f"Error in has_data_in_range: {e}", exc_info=True)
        raise