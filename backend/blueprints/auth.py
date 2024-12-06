from quart import Blueprint, request, jsonify
from services.auth_service import authenticate_user, generate_jwt_token, refresh_jwt_token
from utils.validation import validate_request

auth_blueprint = Blueprint("auth", __name__, url_prefix="/auth")

@auth_blueprint.route("/login", methods=["POST"])
async def login():
    data = await request.get_json()
    if not validate_request(data, ["username", "password"]):
        return jsonify({"success": False, "error": "Invalid or missing fields."}), 400
    
    username = data["username"]
    password = data["password"]
    
    try:
        user = await authenticate_user(username, password)
        if not user:
            return jsonify({"success": False, "error": "Invalid credentials."}), 401
        
        token = generate_jwt_token(user)
        return jsonify({"success": True, "token": token}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@auth_blueprint.route("/refresh", methods=["POST"])
async def refresh_token():
    data = await request.get_json()
    old_token = data.get("token")
    try:
        new_token = refresh_jwt_token(old_token)
        return jsonify({"success": True, "token": new_token}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
