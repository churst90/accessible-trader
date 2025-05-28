# blueprints/__init__.py

from .market import market_blueprint
from .auth import auth_blueprint
from .websocket import websocket_blueprint
from .user import user_blueprint
from .user_credentials import user_credentials_bp
from .trading import trading_blueprint
from .trading_bot import trading_bot_bp

def init_blueprints(app):
    app.register_blueprint(market_blueprint)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(websocket_blueprint)
    app.register_blueprint(user_blueprint)
    app.register_blueprint(user_credentials_bp)
    app.register_blueprint(trading_blueprint)
    app.register_blueprint(trading_bot_bp)
