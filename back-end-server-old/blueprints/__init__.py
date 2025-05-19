# blueprints/__init__.py

from .market import market_blueprint
from .auth import auth_blueprint
from .websocket import websocket_blueprint
from .user import user_blueprint

def init_blueprints(app):
    app.register_blueprint(market_blueprint)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(websocket_blueprint)
    app.register_blueprint(user_blueprint)
