# blueprints/user.py

import logging

from quart import Blueprint, request, g, current_app
from middleware.auth_middleware import jwt_required
from services.user_service import save_user_config, get_user_data
from utils.response import make_success_response, make_error_response

logger = logging.getLogger("user_blueprint")

user_blueprint = Blueprint("user", __name__, url_prefix="/api/user")


@user_blueprint.route("/save_config", methods=["POST"])
@jwt_required
async def save_config():
    data = await request.get_json()
    if not isinstance(data, dict):
        return make_error_response("Expected a JSON object in request body", code=400)

    try:
        await save_user_config(g.user["id"], data)
        return make_success_response(data={"message": "Config saved"})
    except Exception as e:
        logger.error(f"save_user_config error: {e}", exc_info=True)
        return make_error_response("Internal server error", code=500)


@user_blueprint.route("/get_user_data", methods=["GET"])
@jwt_required
async def get_user_data_endpoint():
    try:
        result = await get_user_data(g.user["id"])
        return make_success_response(data=result)
    except Exception as e:
        logger.error(f"get_user_data error: {e}", exc_info=True)
        return make_error_response("Internal server error", code=500)
