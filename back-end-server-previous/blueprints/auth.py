# blueprints/auth.py

import logging

from quart import Blueprint, request, current_app
from utils.validation import validate_request
from utils.response import make_success_response, make_error_response
from services.auth_service import authenticate_user, generate_jwt_token, refresh_jwt_token

logger = logging.getLogger("auth_blueprint")

auth_blueprint = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_blueprint.route("/login", methods=["POST"])
async def login():
    data = await request.get_json()
    if not validate_request(data, ["username", "password"]):
        return make_error_response("Invalid or missing 'username' or 'password'", code=400)

    try:
        user = await authenticate_user(data["username"], data["password"])
    except Exception as e:
        logger.error(f"Authentication error: {e}", exc_info=True)
        return make_error_response("Internal server error", code=500)

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
    data = await request.get_json()
    token = data.get("token")
    if not token:
        return make_error_response("Missing 'token' parameter", code=400)

    try:
        new_token = refresh_jwt_token(token)
        return make_success_response(data={"token": new_token})
    except ValueError as e:  # expired or invalid
        return make_error_response(str(e), code=401)
    except Exception as e:
        logger.error(f"Token refresh error: {e}", exc_info=True)
        return make_error_response("Internal server error", code=500)
