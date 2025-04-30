from quart import request, jsonify, g, current_app
import jwt
from utils.response import make_error_response
from utils.db_utils import fetch_query
import logging

logger = logging.getLogger("AuthMiddleware")

async def jwt_required(func):
    async def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("Missing or invalid Authorization header.")
            return make_error_response("Authorization header missing or invalid", code=401)

        token = auth_header.split("Bearer ")[1]
        try:
            decoded = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
            g.user = {"id": decoded["id"], "username": decoded["username"]}
            logger.info(f"User authenticated: {g.user}")
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

async def role_required(required_role):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            if not hasattr(g, "user") or not g.user:
                logger.warning("Authorization failed: User not authenticated.")
                return make_error_response("User not authenticated", code=403)

            user_id = g.user.get("id")
            user_role = await get_user_role(user_id)
            if not user_role or user_role != required_role:
                logger.warning(f"Authorization failed: User ID {user_id} does not have the required role '{required_role}'.")
                return make_error_response(f"Access denied: Requires '{required_role}' role", code=403)

            logger.info(f"Access granted for user ID {user_id} with role '{user_role}'.")
            return await func(*args, **kwargs)
        return wrapper
    return decorator

async def get_user_role(user_id):
    # This function uses fetch_query which uses the DB pool from current_app.config
    try:
        query = "SELECT role FROM users WHERE id = $1"
        rows = await fetch_query(query, user_id)
        if rows:
            return rows[0]["role"]
        logger.warning(f"No role found for user ID {user_id}.")
        return None
    except Exception as e:
        logger.error(f"Error fetching role for user ID {user_id}: {e}")
        return None
