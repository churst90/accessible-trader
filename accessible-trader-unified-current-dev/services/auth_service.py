# services/auth_service.py

import asyncio # Keep for potential use with bcrypt if needed later
import bcrypt
import jwt
import logging
from datetime import datetime, timedelta
from quart import current_app
from sqlalchemy import select # Import select for SQLAlchemy 2.0 style queries

# Use the new async session scope
from app_extensions.auth_db_setup import auth_db_session_scope
from models.auth_models import User # Your User SQLAlchemy model

logger = logging.getLogger("AuthService")

async def authenticate_user(username, password) -> dict | None:
    """
    Authenticates a user against the 'users' table in the auth_db (userdb)
    using asynchronous database operations.

    Args:
        username (str): The username.
        password (str): The user's password.

    Returns:
        dict | None: A dictionary with user id, username, and role if authentication is successful,
                     None otherwise.
    """
    try:
        async with auth_db_session_scope() as session: # Use the async context manager
            # Asynchronously query the User model
            stmt = select(User).where(User.username == username)
            result = await session.execute(stmt)
            user_record = result.scalars().first() # Get the first User object or None

            if not user_record:
                logger.warning(f"Authentication failed: User '{username}' not found.")
                return None

            # bcrypt.checkpw is synchronous and CPU-bound.
            # For very high throughput, this specific part could be run in a thread:
            # is_valid_password = await asyncio.to_thread(
            #     bcrypt.checkpw, password.encode('utf-8'), user_record.password.encode('utf-8')
            # )
            # However, for typical loads, keeping it inline might be acceptable. Let's keep it inline for now.
            hashed_password_bytes = user_record.password.encode('utf-8') # Ensure it's bytes
            password_bytes = password.encode('utf-8')
            
            is_valid_password = False
            try:
                # This CPU-bound operation could be offloaded if it becomes a bottleneck
                is_valid_password = bcrypt.checkpw(password_bytes, hashed_password_bytes)
            except Exception as e_bcrypt: # Catch potential bcrypt errors like invalid hash format
                logger.error(f"Bcrypt error for user '{username}': {e_bcrypt}", exc_info=True)
                return None


            if is_valid_password:
                logger.info(f"User '{username}' authenticated successfully.")
                return {
                    "id": user_record.id,
                    "username": user_record.username,
                    "role": str(user_record.role) # Ensure role is consistently a string
                }
            else:
                logger.warning(f"Authentication failed: Invalid password for user '{username}'.")
                return None
    except Exception as e:
        logger.error(f"Error during user authentication for '{username}': {e}", exc_info=True)
        return None

async def is_user_authorized(user_id: int, required_role: str | None = None) -> bool:
    """
    Checks if a user exists and optionally if they have a required role
    using asynchronous database operations.

    Args:
        user_id (int): The ID of the user.
        required_role (str | None, optional): The role name required. Defaults to None.

    Returns:
        bool: True if authorized, False otherwise.
    """
    try:
        async with auth_db_session_scope() as session: # Use the async context manager
            # Asynchronously get the User by primary key (more efficient if ID is PK)
            # user_record = await session.get(User, user_id) # Preferred if User.id is simple PK

            # Or, if User.id is not the only PK or for general filtering:
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user_record = result.scalars().first()

            if not user_record:
                logger.warning(f"Authorization check failed: User ID '{user_id}' not found.")
                return False

            if required_role:
                user_role_value = str(user_record.role) # Ensure role is consistently a string
                if user_role_value.lower() != required_role.lower():
                    logger.warning(
                        f"Authorization check failed: User ID '{user_id}' role '{user_role_value}' "
                        f"does not match required role '{required_role.lower()}'."
                    )
                    return False
            
            logger.debug(f"User ID '{user_id}' authorized (Required role: {required_role or 'N/A'}).")
            return True
    except Exception as e:
        logger.error(f"Error during user authorization check for user ID '{user_id}': {e}", exc_info=True)
        return False # Fail closed on error

# --- JWT functions remain the same (CPU-bound, no direct DB I/O) ---

def generate_jwt_token(user: dict) -> str:
    """
    Generates a JWT token for the given user.
    (Content remains unchanged)
    """
    try:
        payload = {
            "id": user["id"],
            "username": user["username"],
            "role": user.get("role", "user"), 
            "exp": datetime.utcnow() + timedelta(seconds=current_app.config["JWT_EXPIRATION_DELTA"]),
            "iat": datetime.utcnow() 
        }
        token = jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")
        logger.info(f"Generated JWT token for user '{user['username']}'.")
        return token
    except Exception as e:
        logger.error(f"Error generating JWT token: {e}", exc_info=True)
        raise ValueError("Failed to generate JWT token") from e

def refresh_jwt_token(token: str) -> str:
    """
    Refreshes an existing JWT token.
    (Content remains unchanged)
    """
    try:
        decoded = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"], options={"verify_exp": True})
        
        new_payload = {
            "id": decoded["id"],
            "username": decoded["username"],
            "role": decoded.get("role", "user"), 
            "exp": datetime.utcnow() + timedelta(seconds=current_app.config["JWT_EXPIRATION_DELTA"]),
            "iat": datetime.utcnow()
        }
        new_token = jwt.encode(new_payload, current_app.config["SECRET_KEY"], algorithm="HS256")
        logger.info(f"Refreshed JWT token for user '{decoded['username']}'.")
        return new_token
    except jwt.ExpiredSignatureError:
        logger.warning("Token refresh failed: Token has expired.")
        raise ValueError("Token has expired.")
    except jwt.InvalidTokenError as e:
        logger.error(f"Token refresh failed: Invalid token - {e}", exc_info=True)
        raise ValueError("Invalid token.")
    except Exception as e:
        logger.error(f"Unexpected error during token refresh: {e}", exc_info=True)
        raise ValueError("Token refresh failed due to an unexpected error.") from e

def decode_jwt_token(token: str) -> dict | None:
    """
    Decodes a JWT token.
    (Content remains unchanged)
    """
    try:
        payload = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"], options={"verify_exp": True})
        logger.debug(f"Decoded JWT token for user '{payload.get('username', 'unknown')}'.")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT decoding failed: Token has expired.")
        return None 
    except jwt.InvalidTokenError as e:
        logger.error(f"JWT decoding failed: Invalid token - {e}", exc_info=True)
        return None 
    except Exception as e:
        logger.error(f"Unexpected error during JWT decoding: {e}", exc_info=True)
        return None