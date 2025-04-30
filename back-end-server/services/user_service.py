# services/user_service.py

import json
import logging
from utils.db_utils import fetch_query, execute_query

logger = logging.getLogger("UserService")

async def save_user_config(user_id: int, config: dict):
    """
    Save or update a user's configuration settings.
    Requires a 'user_configs' table with columns:
        user_id INTEGER PRIMARY KEY,
        config JSONB NOT NULL
    """
    query = """
    INSERT INTO user_configs (user_id, config)
    VALUES ($1, $2::jsonb)
    ON CONFLICT (user_id) DO UPDATE
      SET config = EXCLUDED.config
    """
    payload = json.dumps(config)
    await execute_query(query, user_id, payload)
    logger.info(f"Saved config for user_id={user_id}")

async def get_user_data(user_id: int) -> dict:
    """
    Retrieve a user's configuration settings.
    Returns an empty dict if none found.
    """
    query = "SELECT config FROM user_configs WHERE user_id = $1"
    rows = await fetch_query(query, user_id)
    if rows:
        return rows[0]["config"]
    logger.info(f"No config found for user_id={user_id}, returning empty dict")
    return {}
