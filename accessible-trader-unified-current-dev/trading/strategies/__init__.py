# trading/strategies/__init__.py

"""
The strategies package contains the base class for trading strategies
and common data structures used by them.
"""
from .base_strategy import (
    TradingStrategyBase,
    Signal,
    SignalAction,
    StrategyMarketData
)

__all__ = [
    "TradingStrategyBase",
    "Signal",
    "SignalAction",
    "StrategyMarketData"
]