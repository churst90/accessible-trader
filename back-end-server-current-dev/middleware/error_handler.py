# middleware/error_handler.py
from quart import jsonify

def init_error_handlers(app):
    @app.errorhandler(400)
    async def handle_400_error(error):
        return jsonify({"success": False, "error": "Bad Request", "message": str(error)}), 400

    @app.errorhandler(401)
    async def handle_401_error(error):
        return jsonify({"success": False, "error": "Unauthorized", "message": str(error)}), 401

    @app.errorhandler(404)
    async def handle_404_error(error):
        return jsonify({"success": False, "error": "Not Found", "message": str(error)}), 404

    @app.errorhandler(500)
    async def handle_500_error(error):
        return jsonify({"success": False, "error": "Internal Server Error", "message": str(error)}), 500
