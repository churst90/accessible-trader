# trading/__init__.py

"""
The trading package contains all logic related to automated trading bots,
strategies, and their management.
"""
from .bot import TradingBot
from .bot_manager_service import BotManagerService

__all__ = [
    "TradingBot",
    "BotManagerService"
]

# You might also initialize or register things here if needed at the package level later.