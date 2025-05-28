# app_extensions/db_pool.py
import asyncpg
import os
import logging
from asyncio import sleep
from quart import Quart

logger = logging.getLogger("DBPool")

async def init_db_pool(app: Quart):
    """
    Initialize the database connection pool once at application startup.
    Returns the pool instance which will be stored in app.config["DB_POOL"].
    """
    max_retries = 5
    retry_delay = 5  # seconds

    db_dsn = app.config["OHLCV_DB_CONNECTION_STRING"]
    if not db_dsn:
        logger.critical("OHLCV_DB_CONNECTION_STRING is not defined. Cannot initialize the database pool.")
        raise RuntimeError("Database connection string is required.")

    for attempt in range(1, max_retries + 1):
        try:
            pool = await asyncpg.create_pool(
                dsn=db_dsn,
                min_size=2,
                max_size=10,
                timeout=60
            )
            logger.info("Database pool initialized successfully.")
            return pool
        except Exception as e:
            logger.error(f"Failed to initialize database pool (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await sleep(retry_delay)
            else:
                logger.critical("Maximum retries reached. Database pool initialization failed.")
                raise RuntimeError("Failed to initialize database pool after maximum retries.") from e

async def close_db_pool(app: Quart):
    """
    Close the database connection pool once during application shutdown.
    """
    pool = get_pool(app)
    if pool:
        try:
            await pool.close()
            logger.info("Database pool closed successfully.")
        except Exception as e:
            logger.error(f"Error while closing database pool: {e}")
    else:
        logger.warning("No database pool to close.")

def get_pool(app: Quart):
    """
    Retrieve the database pool from the application config.
    """
    return app.config.get("DB_POOL")
