import bcrypt
import jwt
from datetime import datetime, timedelta
from quart import current_app
from utils.db_utils import fetch_query
import logging

logger = logging.getLogger("AuthService")

async def authenticate_user(username, password):
    query = "SELECT id, username, password_hash FROM users WHERE username = $1"
    try:
        rows = await fetch_query(query, username)
        if not rows:
            logger.warning(f"Authentication failed: User '{username}' not found.")
            return None

        user = rows[0]
        if bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            logger.info(f"User '{username}' authenticated successfully.")
            return {"id": user["id"], "username": user["username"]}
        else:
            logger.warning(f"Authentication failed: Invalid password for user '{username}'.")
            return None
    except Exception as e:
        logger.error(f"Error during user authentication: {e}")
        raise ValueError("Failed to authenticate user")

def generate_jwt_token(user):
    try:
        payload = {
            "id": user["id"],
            "username": user["username"],
            "exp": datetime.utcnow() + timedelta(seconds=current_app.config["JWT_EXPIRATION_DELTA"]),
        }
        token = jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")
        logger.info(f"Generated JWT token for user '{user['username']}'.")
        return token
    except Exception as e:
        logger.error(f"Error generating JWT token: {e}")
        raise ValueError("Failed to generate JWT token")

def refresh_jwt_token(token):
    try:
        decoded = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
        new_payload = {
            "id": decoded["id"],
            "username": decoded["username"],
            "exp": datetime.utcnow() + timedelta(seconds=current_app.config["JWT_EXPIRATION_DELTA"]),
        }
        new_token = jwt.encode(new_payload, current_app.config["SECRET_KEY"], algorithm="HS256")
        logger.info(f"Refreshed JWT token for user '{decoded['username']}'.")
        return new_token
    except jwt.ExpiredSignatureError:
        logger.warning("Token refresh failed: Token has expired.")
        raise ValueError("Token has expired.")
    except jwt.InvalidTokenError as e:
        logger.error(f"Token refresh failed: Invalid token - {e}")
        raise ValueError("Invalid token.")

def decode_jwt_token(token):
    try:
        payload = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
        logger.debug(f"Decoded JWT token for user '{payload['username']}'.")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Decoding failed: Token has expired.")
        raise ValueError("Token has expired.")
    except jwt.InvalidTokenError as e:
        logger.error(f"Decoding failed: Invalid token - {e}")
        raise ValueError("Invalid token.")

async def is_user_authorized(user_id, required_role=None):
    # Uses DB and no direct config references, so it's fine
    query = "SELECT role FROM users WHERE id = $1"
    try:
        rows = await fetch_query(query, user_id)
        if not rows:
            logger.warning(f"Authorization failed: User ID '{user_id}' not found.")
            return False

        user_role = rows[0]["role"]
        if required_role and user_role != required_role:
            logger.warning(f"Authorization failed: User ID '{user_id}' does not have the required role '{required_role}'.")
            return False

        logger.info(f"User ID '{user_id}' authorized successfully.")
        return True
    except Exception as e:
        logger.error(f"Error during user authorization: {e}")
        raise ValueError("Failed to authorize user")
