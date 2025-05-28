# blueprints/auth.py

import logging
import bcrypt # For password hashing
from sqlalchemy.exc import IntegrityError # To catch duplicate username/email errors
from sqlalchemy import select # For checking existing user

from quart import Blueprint, request, current_app
from utils.validation import validate_request # Assuming you might add more specific validation here
from utils.response import make_success_response, make_error_response
from services.auth_service import authenticate_user, generate_jwt_token, refresh_jwt_token

# --- Add these imports ---
from models.auth_models import User # Your User SQLAlchemy model
from app_extensions.auth_db_setup import auth_db_session_scope # Your async session scope

logger = logging.getLogger("auth_blueprint")

auth_blueprint = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_blueprint.route("/login", methods=["POST"])
async def login():
    # ... your existing login code ...
    data = await request.get_json()
    if not data or not validate_request(data, ["username", "password"]): # Ensure data is not None
        return make_error_response("Invalid or missing 'username' or 'password'", code=400)

    try:
        user = await authenticate_user(data["username"], data["password"])
    except Exception as e:
        logger.error(f"Authentication error: {e}", exc_info=True)
        return make_error_response("Internal server error during authentication", code=500)

    if not user:
        return make_error_response("Invalid credentials", code=401)

    try:
        token = generate_jwt_token(user)
    except Exception as e:
        logger.error(f"Token generation error: {e}", exc_info=True)
        return make_error_response("Failed to generate token", code=500)

    return make_success_response(data={"token": token})


@auth_blueprint.route("/refresh", methods=["POST"])
async def refresh_token():
    # ... your existing refresh token code ...
    data = await request.get_json()
    token = data.get("token") if data else None # Ensure data is not None
    if not token:
        return make_error_response("Missing 'token' parameter", code=400)

    try:
        new_token = refresh_jwt_token(token)
        return make_success_response(data={"token": new_token})
    except ValueError as e:
        return make_error_response(str(e), code=401)
    except Exception as e:
        logger.error(f"Token refresh error: {e}", exc_info=True)
        return make_error_response("Internal server error during token refresh", code=500)

# --- NEW REGISTRATION ENDPOINT ---
@auth_blueprint.route("/register", methods=["POST"])
async def register():
    """
    Registers a new user.
    Expects JSON payload with: username, email, password.
    """
    data = await request.get_json()
    if not data:
        return make_error_response("Missing JSON payload", code=400)

    username = data.get("username")
    email = data.get("email")
    password = data.get("password")

    # Basic Validation
    if not username or not isinstance(username, str) or len(username) < 3:
        return make_error_response("Username must be a string with at least 3 characters.", code=400)
    if not email or not isinstance(email, str) or "@" not in email: # Very basic email check
        return make_error_response("A valid email is required.", code=400)
    if not password or not isinstance(password, str) or len(password) < 8: # Example: min 8 chars
        return make_error_response("Password must be a string with at least 8 characters.", code=400)

    # Hash the password
    try:
        # bcrypt.gensalt() can be CPU intensive, run in thread pool for async app
        salt = await current_app.loop.run_in_executor(None, bcrypt.gensalt)
        hashed_password_bytes = await current_app.loop.run_in_executor(
            None, bcrypt.hashpw, password.encode('utf-8'), salt
        )
        hashed_password = hashed_password_bytes.decode('utf-8')
    except Exception as e_bcrypt:
        logger.error(f"Password hashing error during registration for {username}: {e_bcrypt}", exc_info=True)
        return make_error_response("Error processing registration (hashing).", code=500)

    async with auth_db_session_scope() as session:
        try:
            # Check if username or email already exists
            stmt_check_user = select(User).where((User.username == username) | (User.email == email))
            result_check = await session.execute(stmt_check_user)
            existing_user = result_check.scalars().first()

            if existing_user:
                if existing_user.username == username:
                    return make_error_response("Username already exists.", code=409) # 409 Conflict
                if existing_user.email == email:
                    return make_error_response("Email address already registered.", code=409)

            # Create new user
            new_user = User(
                username=username,
                email=email,
                password=hashed_password, # Store the hashed password
                role='user' # Default role
            )
            session.add(new_user)
            # The session_scope will commit if no exceptions

            logger.info(f"User '{username}' registered successfully.")
            # Optionally, you could generate and return a JWT here for auto-login after registration
            # For now, just a success message. Client can then proceed to login.
            return make_success_response(
                data={"message": "Registration successful. Please log in."},
                code=201 # 201 Created
            )
        except IntegrityError as e_int: # Should be caught by the explicit check above, but as a fallback
            logger.warning(f"IntegrityError during registration for {username}: {e_int.orig}")
            # Determine if it's username or email, though the check above is better
            return make_error_response("Username or email might already be taken (integrity).", code=409)
        except Exception as e_db:
            logger.error(f"Database error during registration for {username}: {e_db}", exc_info=True)
            return make_error_response("Could not complete registration due to a server error.", code=500)