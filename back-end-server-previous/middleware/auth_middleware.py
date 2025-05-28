# middleware/auth_middleware.py

import jwt
import logging
from functools import wraps
from quart import request, g, current_app
from utils.response import make_error_response
from utils.db_utils import fetch_query

logger = logging.getLogger("AuthMiddleware")

def jwt_required(func):
    """
    Decorator to ensure a valid JWT is present in the Authorization header.
    Preserves the original function name so Quart can register multiple routes.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("Missing or invalid Authorization header.")
            return make_error_response("Authorization header missing or invalid", code=401)

        token = auth_header.split("Bearer ", 1)[1]
        try:
            decoded = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
            g.user = {"id": decoded["id"], "username": decoded["username"]}
            logger.info(f"User authenticated: {g.user['username']}")
        except jwt.ExpiredSignatureError:
            logger.warning("JWT validation failed: Token has expired.")
            return make_error_response("Token expired", code=401)
        except jwt.InvalidTokenError as e:
            logger.error(f"JWT validation failed: Invalid token. Details: {e}")
            return make_error_response("Invalid token", code=401)
        except Exception as e:
            logger.error(f"Unexpected error during JWT validation: {e}")
            return make_error_response("Authorization failed", code=500)

        return await func(*args, **kwargs)
    return wrapper

def role_required(required_role):
    """
    Decorator factory to enforce that the user has a specific role.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not getattr(g, "user", None):
                logger.warning("Authorization failed: User not authenticated.")
                return make_error_response("User not authenticated", code=403)

            user_id = g.user["id"]
            # Fetch user role from DB
            try:
                rows = await fetch_query("SELECT role FROM users WHERE id = $1", user_id)
                user_role = rows[0]["role"] if rows else None
            except Exception as e:
                logger.error(f"Error fetching user role: {e}")
                return make_error_response("Authorization error", code=500)

            if user_role != required_role:
                logger.warning(
                    f"Authorization failed: User {user_id} role '{user_role}' != required '{required_role}'."
                )
                return make_error_response(f"Access denied: {required_role} only", code=403)

            logger.info(f"Access granted for user {user_id} with role '{user_role}'.")
            return await func(*args, **kwargs)
        return wrapper
    return decorator
