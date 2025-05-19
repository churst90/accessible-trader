# utils/db-utils.py

import logging
from quart import current_app
from datetime import datetime
from typing import Optional, List, Dict

logger = logging.getLogger("DatabaseUtils")


async def fetch_query(query: str, *params):
    """
    Execute a SELECT-style query with positional parameters.
    Returns a list of records.
    """
    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise RuntimeError("Database connection pool is not initialized.")
    async with pool.acquire() as conn:
        try:
            result = await conn.fetch(query, *params)
            logger.debug(f"fetch_query: {query} | params={params}")
            return result
        except Exception as e:
            logger.error(f"Error in fetch_query: {e} | Query: {query}")
            raise


async def execute_query(query: str, *params):
    """
    Execute an INSERT/UPDATE/DELETE-style query with positional parameters.
    """
    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise RuntimeError("Database connection pool is not initialized.")
    async with pool.acquire() as conn:
        try:
            await conn.execute(query, *params)
            logger.debug(f"execute_query: {query} | params={params}")
        except Exception as e:
            logger.error(f"Error in execute_query: {e} | Query: {query}")
            raise


async def fetch_ohlcv_from_db(
    market: str,
    provider: str,
    symbol: str,
    timeframe: str,
    since: Optional[int] = None,
    before: Optional[int] = None,
    limit: Optional[int] = None
) -> List[Dict]:
    """
    Fetch up to `limit` bars since `since` (ms) and before `before` (ms).
    Returns oldest?newest.
    """
    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise RuntimeError("Database connection pool is not initialized.")

    # Base SQL and parameters
    sql = (
        "SELECT timestamp, open, high, low, close, volume "
        "FROM ohlcv_data "
        "WHERE market=$1 AND provider=$2 AND symbol=$3 AND timeframe=$4"
    )
    params: List = [market, provider, symbol, timeframe]
    idx = 5

    # Optional 'since' filter
    if since is not None:
        since_dt = datetime.fromtimestamp(since / 1000.0)
        sql += f" AND timestamp >= ${idx}"
        params.append(since_dt)
        idx += 1

    # Optional 'before' filter
    if before is not None:
        before_dt = datetime.fromtimestamp(before / 1000.0)
        sql += f" AND timestamp < ${idx}"
        params.append(before_dt)
        idx += 1

    # Ordering
    sql += " ORDER BY timestamp ASC"

    # Optional 'limit'
    if limit is not None:
        sql += f" LIMIT ${idx}"
        params.append(int(limit))

    # Execute
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(sql, *params)
            logger.debug(f"fetch_ohlcv_from_db returned {len(rows)} rows | params={params}")
            return [
                {
                    "timestamp": int(r["timestamp"].timestamp() * 1000),
                    "open":      r["open"],
                    "high":      r["high"],
                    "low":       r["low"],
                    "close":     r["close"],
                    "volume":    r["volume"],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Error in fetch_ohlcv_from_db: {e} | Query: {sql}")
            raise


async def fetch_historical_ohlcv_from_db(
    market: str,
    provider: str,
    symbol: str,
    timeframe: str,
    before: Optional[int],
    limit: int = 100
) -> List[Dict]:
    """
    Fetch up to `limit` bars older than `before` (ms).
    Returns oldest?newest.
    """
    if before is None:
        return []

    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise RuntimeError("Database connection pool is not initialized.")

    before_dt = datetime.fromtimestamp(before / 1000.0)
    sql = (
        "SELECT timestamp, open, high, low, close, volume "
        "FROM ohlcv_data "
        "WHERE market=$1 AND provider=$2 AND symbol=$3 "
        "  AND timeframe=$4 AND timestamp < $5 "
        "ORDER BY timestamp DESC "
        "LIMIT $6"
    )
    params = [market, provider, symbol, timeframe, before_dt, limit]

    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(sql, *params)
            bars = list(reversed([
                {
                    "timestamp": int(r["timestamp"].timestamp() * 1000),
                    "open":      r["open"],
                    "high":      r["high"],
                    "low":       r["low"],
                    "close":     r["close"],
                    "volume":    r["volume"],
                }
                for r in rows
            ]))
            logger.debug(f"fetch_historical_ohlcv_from_db returned {len(bars)} bars before {before}")
            return bars
        except Exception as e:
            logger.error(f"Error in fetch_historical_ohlcv_from_db: {e}")
            raise


async def insert_ohlcv_to_db(
    market: str,
    provider: str,
    symbol: str,
    timeframe: str,
    data: List[Dict]
):
    """
    Bulk upsert OHLCV bars into the raw table.
    """
    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise RuntimeError("Database connection pool is not initialized.")

    sql = """
    INSERT INTO ohlcv_data
      (market,provider,symbol,timeframe,timestamp,open,high,low,close,volume)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
    ON CONFLICT (market,provider,symbol,timeframe,timestamp) DO UPDATE
      SET open=EXCLUDED.open,
          high=EXCLUDED.high,
          low=EXCLUDED.low,
          close=EXCLUDED.close,
          volume=EXCLUDED.volume
    """

    params_list = [
        (
            market,
            provider,
            symbol,
            timeframe,
            datetime.fromtimestamp(bar["timestamp"] / 1000),
            bar["open"],
            bar["high"],
            bar["low"],
            bar["close"],
            bar["volume"]
        )
        for bar in data
    ]

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(sql, params_list)
            logger.debug(f"insert_ohlcv_to_db upserted {len(params_list)} bars")
