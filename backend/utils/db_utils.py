import logging
from quart import current_app
import pandas as pd

logger = logging.getLogger("DatabaseUtils")

async def fetch_query(query, *params):
    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise RuntimeError("Database connection pool is not initialized.")
    async with pool.acquire() as conn:
        try:
            result = await conn.fetch(query, *params)
            logger.debug(f"Executed query: {query} with params: {params}")
            return result
        except Exception as e:
            logger.error(f"Error executing fetch query: {query} with params {params}. Error: {e}")
            raise ValueError(f"Database fetch operation failed: {e}")

async def execute_query(query, *params):
    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise RuntimeError("Database connection pool is not initialized.")
    async with pool.acquire() as conn:
        try:
            await conn.execute(query, *params)
            logger.debug(f"Executed query: {query} with params: {params}")
        except Exception as e:
            logger.error(f"Error executing query: {query} with params {params}. Error: {e}")
            raise ValueError(f"Database execute operation failed: {e}")

async def fetch_ohlcv_from_db(market, exchange, symbol, timeframe, since=None, limit=None):
    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise RuntimeError("Database connection pool is not initialized.")

    base_query = """
    SELECT timestamp, open, high, low, close, volume
    FROM ohlcv_data
    WHERE market = $1 AND exchange = $2 AND symbol = $3 AND timeframe = $4
    """
    params = [market, exchange, symbol, timeframe]

    if since is not None:
        # Convert since (ms) to datetime
        since_dt = pd.Timestamp(since, unit="ms").to_pydatetime()
        base_query += " AND timestamp >= $5"
        params.append(since_dt)

    base_query += " ORDER BY timestamp ASC"

    if limit is not None:
        base_query += f" LIMIT {int(limit)}"

    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(base_query, *params)
            logger.info(
                f"Fetched {len(rows)} rows from database for market='{market}', "
                f"exchange='{exchange}', symbol='{symbol}', timeframe='{timeframe}'."
            )
            return [
                {
                    "timestamp": int(row["timestamp"].timestamp() * 1000),
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(
                f"Error fetching OHLCV data for market='{market}', exchange='{exchange}', "
                f"symbol='{symbol}', timeframe='{timeframe}': {e}"
            )
            raise ValueError(f"Database fetch operation for OHLCV data failed: {e}")

async def insert_ohlcv_to_db(market, exchange, symbol, timeframe, data):
    pool = current_app.config.get("DB_POOL")
    if not pool:
        raise RuntimeError("Database connection pool is not initialized.")

    query = """
    INSERT INTO ohlcv_data (market, exchange, symbol, timeframe, timestamp, open, high, low, close, volume)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
    ON CONFLICT (market, exchange, symbol, timeframe, timestamp) DO UPDATE
    SET open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume
    """

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                await conn.executemany(query, [
                    (
                        market,
                        exchange,
                        symbol,
                        timeframe,
                        pd.Timestamp(row["timestamp"], unit="ms").to_pydatetime(),
                        row["open"], row["high"], row["low"], row["close"], row["volume"]
                    )
                    for row in data
                ])
                logger.info(
                    f"Inserted/updated {len(data)} rows into database for "
                    f"market='{market}', exchange='{exchange}', symbol='{symbol}' with timeframe='{timeframe}'."
                )
        except Exception as e:
            logger.error(
                f"Error inserting OHLCV data for market='{market}', exchange='{exchange}', "
                f"symbol='{symbol}', timeframe='{timeframe}': {e}"
            )
            raise ValueError(f"Database insert operation for OHLCV data failed: {e}")
