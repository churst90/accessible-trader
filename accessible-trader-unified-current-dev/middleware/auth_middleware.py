# middleware/auth_middleware.py

import jwt
import logging
from functools import wraps
from quart import request, g, current_app # current_app is needed for SECRET_KEY
from sqlalchemy import select
from typing import Optional, Dict, Any # Added for type hints

from app_extensions.auth_db_setup import auth_db_session_scope
from models.auth_models import User
from utils.response import make_error_response

logger = logging.getLogger("AuthMiddleware") # Or __name__ if preferred

def jwt_required(func):
    """
    Decorator to ensure a valid JWT is present in the Authorization header.
    Sets g.user with id, username, and role from the token.
    This decorator is intended for HTTP request handlers.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("Missing or invalid Authorization header format for HTTP request.")
            return make_error_response("Authorization header missing or invalid format", code=401)

        token = auth_header.split("Bearer ", 1)[1]
        try:
            # Use the new helper for the core decoding logic
            user_info = get_user_from_token(token) # Calls the new function
            if not user_info:
                # get_user_from_token logs the specific error (expired, invalid)
                return make_error_response("Invalid or expired token.", code=401)

            g.user = user_info # type: ignore [attr-defined]
            logger.info(f"User authenticated via JWT for HTTP request: {g.user['username']} (Role: {g.user.get('role')})") # type: ignore [attr-defined]

        except Exception as e: # Catch-all for unexpected issues if get_user_from_token itself raised something weird
            logger.error(f"Unexpected error during HTTP JWT validation or context setup: {e}", exc_info=True)
            return make_error_response("Authorization process failed", code=500)

        return await func(*args, **kwargs)
    return wrapper

def role_required(required_role: str):
    """
    Decorator factory to enforce that the authenticated user (from JWT in g.user)
    has a specific role. The role is first checked against g.user (populated by jwt_required),
    then re-verified against the database for up-to-date accuracy.
    Intended for HTTP request handlers that run after @jwt_required.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not hasattr(g, "user") or not g.user: # type: ignore [attr-defined]
                logger.warning("Role check failed: User not authenticated (g.user not set). Ensure @jwt_required runs first.")
                return make_error_response("User not authenticated", code=401)

            user_id = g.user.get("id") # type: ignore [attr-defined]
            user_role_from_context = g.user.get("role") # type: ignore [attr-defined]

            if not user_id: # Role from context check is less critical if ID is missing
                logger.warning(f"Role check failed: User ID missing in g.user. Context: {g.user}") # type: ignore [attr-defined]
                return make_error_response("Invalid authentication context (ID missing)", code=403)

            # 1. Re-verify role from database for accuracy (defense in depth)
            #    Even if JWT role was checked, DB is the source of truth.
            try:
                async with auth_db_session_scope() as session:
                    stmt = select(User.role).where(User.id == user_id)
                    result = await session.execute(stmt)
                    user_role_from_db_enum = result.scalars().first()

                if user_role_from_db_enum is None:
                    logger.error(f"Role re-verification critical error: User ID {user_id} not found in database, but JWT exists. Possible data inconsistency.")
                    return make_error_response("User account not found or inactive.", code=403)

                user_role_from_db_str = str(user_role_from_db_enum).lower()

                if user_role_from_db_str != required_role.lower():
                    logger.warning(
                        f"Authorization failed (DB re-verification): User {user_id} ({g.user.get('username')}) " # type: ignore [attr-defined]
                        f"database role '{user_role_from_db_str}' does not match required role '{required_role}'. "
                        f"Context role was '{user_role_from_context}'. Access Denied."
                    )
                    return make_error_response(f"Access denied. Requires '{required_role}' role.", code=403)
                
                # Update g.user.role to reflect the true current role from DB if different from token
                if user_role_from_context and user_role_from_context.lower() != user_role_from_db_str:
                     logger.warning(
                        f"Role consistency alert for User {user_id}: Context role '{user_role_from_context}' differs from DB role '{user_role_from_db_str}'. "
                        f"Using DB role for authorization. Token may be stale."
                    )
                g.user["role"] = user_role_from_db_str # type: ignore [attr-defined]

                logger.info(f"Access granted for user {user_id} ({g.user.get('username')}) with DB-verified role '{user_role_from_db_str}' for required role '{required_role}'.") # type: ignore [attr-defined]
            
            except Exception as e_db_role:
                logger.error(f"Error during role re-verification from DB for user {user_id}: {e_db_role}", exc_info=True)
                return make_error_response("Authorization check error during DB lookup.", code=500)
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# --- NEW HELPER FUNCTION ---
def get_user_from_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decodes a JWT token and returns user information if valid and not expired.
    This function can be called independently, for example, by the WebSocket handler
    to authenticate a user based on a token passed in a message or query parameter.

    Args:
        token (str): The JWT token string.

    Returns:
        Optional[Dict[str, Any]]: A dictionary containing user 'id', 'username', and 'role'
                                  if the token is valid. Returns None otherwise.
                                  The 'role' will default to "user" if not present in the token.
    """
    if not token:
        logger.debug("get_user_from_token: No token provided.")
        return None
    try:
        # Ensure current_app is available. This should be fine in a running Quart app.
        secret_key = current_app.config.get("SECRET_KEY")
        if not secret_key:
            logger.error("JWT decoding failed in get_user_from_token: SECRET_KEY not configured.")
            # Raising an error might be appropriate here if SECRET_KEY is essential for all ops
            raise ValueError("SECRET_KEY is not configured for JWT operations.")

        decoded_payload = jwt.decode(
            token,
            secret_key,
            algorithms=["HS256"],
            options={"verify_exp": True} # Verifies 'exp' claim
        )
        
        user_id = decoded_payload.get("id")
        username = decoded_payload.get("username")

        if not user_id or not username:
            logger.warning(f"JWT decoding: Decoded token missing 'id' or 'username'. Payload: {decoded_payload}")
            return None # Essential identity information is missing

        user_details = {
            "id": user_id,
            "username": username,
            "role": decoded_payload.get("role", "user") # Default role if not in token
        }
        
        logger.debug(f"Token successfully decoded via get_user_from_token for user: {user_details['username']}")
        return user_details

    except jwt.ExpiredSignatureError:
        logger.warning("JWT decoding failed in get_user_from_token: Token has expired.")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT decoding failed in get_user_from_token: Invalid token. Details: {e}")
        return None
    except Exception as e: # Catch any other unexpected errors during decoding
        logger.error(f"Unexpected error during JWT decoding in get_user_from_token: {e}", exc_info=True)
        return None