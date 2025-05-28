# services/user_service.py

import json # Keep for any direct JSON manipulation if needed, though SQLAlchemy handles JSON types
import logging
from sqlalchemy import select, update # Import select and update

# Use the new async session scope for user_configs_db
from app_extensions.user_configs_db_setup import user_configs_db_session_scope
from models.user_config_models import UserGeneralPreference # Your SQLAlchemy model

logger = logging.getLogger("UserService")

async def save_user_config(user_id: int, config_data: dict):
    """
    Save or update a user's general preferences in the user_configs_db asynchronously.
    Uses the UserGeneralPreference ORM model.

    Args:
        user_id (int): The ID of the user (links to users.id in userdb).
        config_data (dict): A dictionary containing preference data.
                            Expected keys: 'ui_theme', 'default_chart_market', etc.
                            and 'other_settings_json' for unstructured data.
    Raises:
        Exception: Propagates database or other unexpected errors.
    """
    log_prefix = f"UserService (save_user_config, User: {user_id}):"
    logger.debug(f"{log_prefix} Attempting to save preferences: {config_data}")

    try:
        async with user_configs_db_session_scope() as session: # Async session scope
            # Check if preference for this user_id already exists
            stmt_select = select(UserGeneralPreference).where(UserGeneralPreference.user_id == user_id)
            result = await session.execute(stmt_select)
            preference = result.scalars().first()

            if not preference:
                logger.debug(f"{log_prefix} No existing preference found. Creating new one.")
                preference = UserGeneralPreference(user_id=user_id)
                # Set initial values from config_data or defaults
                preference.ui_theme = config_data.get('ui_theme', 'light') # Example default
                preference.default_chart_market = config_data.get('default_chart_market')
                preference.default_chart_provider = config_data.get('default_chart_provider')
                preference.default_chart_timeframe = config_data.get('default_chart_timeframe')
                if 'other_settings_json' in config_data:
                    if isinstance(config_data['other_settings_json'], dict):
                        preference.other_settings_json = config_data['other_settings_json']
                    else:
                        logger.warning(f"{log_prefix} Received non-dict type for 'other_settings_json'. Skipping.")
                        preference.other_settings_json = {} # Default to empty dict
                else:
                    preference.other_settings_json = {}
                
                session.add(preference) # Add the new preference object to the session
                logger.info(f"{log_prefix} New preference record created and added to session.")
            else:
                logger.debug(f"{log_prefix} Existing preference found. Updating fields.")
                # Update existing preference object
                updated_fields = []
                if 'ui_theme' in config_data and preference.ui_theme != config_data['ui_theme']:
                    preference.ui_theme = config_data['ui_theme']
                    updated_fields.append('ui_theme')
                if 'default_chart_market' in config_data and preference.default_chart_market != config_data['default_chart_market']:
                    preference.default_chart_market = config_data['default_chart_market']
                    updated_fields.append('default_chart_market')
                if 'default_chart_provider' in config_data and preference.default_chart_provider != config_data['default_chart_provider']:
                    preference.default_chart_provider = config_data['default_chart_provider']
                    updated_fields.append('default_chart_provider')
                if 'default_chart_timeframe' in config_data and preference.default_chart_timeframe != config_data['default_chart_timeframe']:
                    preference.default_chart_timeframe = config_data['default_chart_timeframe']
                    updated_fields.append('default_chart_timeframe')
                
                if 'other_settings_json' in config_data:
                    if isinstance(config_data['other_settings_json'], dict):
                        # For JSON fields, you might want to merge or replace. Here, we replace.
                        if preference.other_settings_json != config_data['other_settings_json']:
                             preference.other_settings_json = config_data['other_settings_json']
                             updated_fields.append('other_settings_json')
                    else:
                        logger.warning(f"{log_prefix} Received non-dict type for 'other_settings_json' during update. Skipping.")
                
                if updated_fields:
                    # The changes to 'preference' attributes are tracked by SQLAlchemy.
                    # The commit (handled by session_scope) will persist them.
                    logger.info(f"{log_prefix} Updated fields: {', '.join(updated_fields)}.")
                else:
                    logger.info(f"{log_prefix} No changes detected in provided config_data for existing preferences.")

            # The session_scope context manager will handle commit on successful exit
            # or rollback on exception.
        logger.info(f"{log_prefix} Successfully saved/updated general preferences for user_id={user_id}")

    except Exception as e:
        # The session_scope will handle rollback.
        logger.error(f"{log_prefix} Error saving user general preferences: {e}", exc_info=True)
        raise # Re-raise to be handled by the calling blueprint

async def get_user_data(user_id: int) -> dict:
    """
    Retrieve a user's general preferences from the user_configs_db asynchronously.
    Uses the UserGeneralPreference ORM model.

    Args:
        user_id (int): The ID of the user.

    Returns:
        dict: A dictionary of the user's preferences. Returns an empty dict if not found.
    Raises:
        Exception: Propagates database or other unexpected errors if they occur during fetch.
    """
    log_prefix = f"UserService (get_user_data, User: {user_id}):"
    logger.debug(f"{log_prefix} Attempting to retrieve preferences.")
    try:
        async with user_configs_db_session_scope() as session: # Async session scope
            stmt = select(UserGeneralPreference).where(UserGeneralPreference.user_id == user_id)
            result = await session.execute(stmt)
            preference = result.scalars().first()
            
            if preference:
                user_prefs = {
                    "user_id": preference.user_id,
                    "ui_theme": preference.ui_theme,
                    "default_chart_market": preference.default_chart_market,
                    "default_chart_provider": preference.default_chart_provider,
                    "default_chart_timeframe": preference.default_chart_timeframe,
                    "other_settings_json": preference.other_settings_json if preference.other_settings_json else {}
                }
                logger.debug(f"{log_prefix} Retrieved general preferences.")
                return user_prefs
            
            logger.info(f"{log_prefix} No general preferences found, returning empty dict.")
            return {}
    except Exception as e:
        # The session_scope will handle rollback (though not relevant for a read operation).
        logger.error(f"{log_prefix} Error retrieving user general preferences: {e}", exc_info=True)
        # Decide on error propagation: re-raise or return empty/error indicator.
        # Re-raising allows the blueprint to handle it (e.g., return 500).
        raise