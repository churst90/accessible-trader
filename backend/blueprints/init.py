from blueprints.market import market_blueprint
from blueprints.auth import auth_blueprint
from blueprints.websocket import websocket_blueprint

def init_blueprints(app):
    """
    Register all blueprints to the given Quart app.
    """
    app.register_blueprint(market_blueprint)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(websocket_blueprint)  # Include the websocket blueprint
