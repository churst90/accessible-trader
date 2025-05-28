# trading/strategies/sma_crossover_strategy.py

import logging
from typing import Any, Dict, List, Optional

# Imports from your project
from trading.strategies.base_strategy import TradingStrategyBase, Signal, SignalAction, StrategyMarketData
from plugins.base import OHLCVBar, Order, Position, Balance # For type hinting if needed directly

logger = logging.getLogger(__name__)

class SMACrossoverStrategy(TradingStrategyBase):
    """
    A simple Moving Average (SMA) Crossover trading strategy.
    - Generates a BUY signal when the short-term SMA crosses above the long-term SMA.
    - Generates a SELL signal when the short-term SMA crosses below the long-term SMA.
    """
    strategy_key: str = "sma_crossover"
    strategy_name: str = "SMA Crossover"
    strategy_description: str = "Trades based on the crossover of two simple moving averages."

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        # Default parameters if not provided
        self.short_window: int = self.params.get("short_window", 10)
        self.long_window: int = self.params.get("long_window", 30)
        self.ohlcv_source: str = self.params.get("source_column", "close").lower() # e.g., 'close', 'open', 'hl2', 'hlc3'
        
        if not isinstance(self.short_window, int) or self.short_window <= 0:
            raise ValueError("SMA Crossover: 'short_window' parameter must be a positive integer.")
        if not isinstance(self.long_window, int) or self.long_window <= 0:
            raise ValueError("SMA Crossover: 'long_window' parameter must be a positive integer.")
        if self.short_window >= self.long_window:
            raise ValueError("SMA Crossover: 'short_window' must be less than 'long_window'.")
        if self.ohlcv_source not in ['open', 'high', 'low', 'close', 'hl2', 'hlc3', 'ohlc4']:
            logger.warning(f"SMA Crossover: Invalid 'source_column' ({self.ohlcv_source}). Defaulting to 'close'.")
            self.ohlcv_source = 'close'

        logger.info(
            f"SMACrossoverStrategy initialized with: Short Window={self.short_window}, "
            f"Long Window={self.long_window}, Source={self.ohlcv_source}"
        )

    def _calculate_sma(self, data_points: List[float], window: int) -> List[Optional[float]]:
        """Calculates Simple Moving Average."""
        if window <= 0 or len(data_points) == 0:
            return [None] * len(data_points)
        
        sma_values: List[Optional[float]] = [None] * (window - 1) # Fill initial points with None
        for i in range(window -1, len(data_points)):
            window_slice = data_points[i - window + 1 : i + 1]
            if len(window_slice) == window: # Ensure full window for calculation
                sma_values.append(sum(window_slice) / window)
            else: # Should not happen if data_points has enough length
                sma_values.append(None)
        return sma_values

    def _get_source_prices(self, ohlcv_bars: List[OHLCVBar]) -> List[float]:
        """Extracts the source price for SMA calculation from OHLCV bars."""
        prices = []
        for bar in ohlcv_bars:
            if self.ohlcv_source == 'open': prices.append(bar['open'])
            elif self.ohlcv_source == 'high': prices.append(bar['high'])
            elif self.ohlcv_source == 'low': prices.append(bar['low'])
            elif self.ohlcv_source == 'close': prices.append(bar['close'])
            elif self.ohlcv_source == 'hl2': prices.append((bar['high'] + bar['low']) / 2)
            elif self.ohlcv_source == 'hlc3': prices.append((bar['high'] + bar['low'] + bar['close']) / 3)
            elif self.ohlcv_source == 'ohlc4': prices.append((bar['open'] + bar['high'] + bar['low'] + bar['close']) / 4)
            else: # Should default to close based on __init__
                 prices.append(bar['close'])
        return prices

    async def analyze(
        self,
        market_data: StrategyMarketData,
        account_balance: Dict[str, Balance],
        open_positions: List[Position],
        open_orders: List[Order]
    ) -> List[Signal]:
        """
        Analyzes market data for SMA crossover signals.
        """
        signals: List[Signal] = []
        symbol = market_data["symbol"]
        ohlcv_bars = market_data["ohlcv_bars"]
        instrument_details = market_data.get("instrument_details") # For order sizing/precision

        if not ohlcv_bars or len(ohlcv_bars) < self.long_window:
            logger.debug(f"{self.strategy_key} ({symbol}): Not enough data for SMA calculation (need {self.long_window}, got {len(ohlcv_bars)}). Holding.")
            signals.append({"action": SignalAction.HOLD, "symbol": symbol, "strategy_name": self.strategy_key})
            return signals

        source_prices = self._get_source_prices(ohlcv_bars)
        short_sma_values = self._calculate_sma(source_prices, self.short_window)
        long_sma_values = self._calculate_sma(source_prices, self.long_window)

        # We need at least two points of each SMA to detect a crossover
        if len(short_sma_values) < 2 or len(long_sma_values) < 2 or \
           short_sma_values[-1] is None or short_sma_values[-2] is None or \
           long_sma_values[-1] is None or long_sma_values[-2] is None:
            logger.debug(f"{self.strategy_key} ({symbol}): Not enough SMA values to detect crossover. Holding.")
            signals.append({"action": SignalAction.HOLD, "symbol": symbol, "strategy_name": self.strategy_key})
            return signals

        # Current and previous SMA values
        current_short_sma = short_sma_values[-1]
        prev_short_sma = short_sma_values[-2]
        current_long_sma = long_sma_values[-1]
        prev_long_sma = long_sma_values[-2]

        # Determine current position for the symbol (simplified: assumes one position per symbol)
        current_position_amount = 0.0
        is_long = False
        is_short = False
        for pos in open_positions:
            if pos.get("symbol") == symbol:
                current_position_amount = pos.get("amount", 0.0)
                if pos.get("side", "").lower() == "long" or (pos.get("side", "").lower() == "buy" and current_position_amount > 0):
                    is_long = True
                elif pos.get("side", "").lower() == "short" or (pos.get("side", "").lower() == "sell" and current_position_amount < 0): # CCXT might use negative amount for short
                    is_short = True
                break
        
        # Order sizing - very basic example: trade a fixed amount or % of quote currency if available
        order_amount = self.params.get("order_amount_fixed", 0.01) # Example: 0.01 BTC
        # TODO: Implement more sophisticated order sizing based on risk, available balance, instrument precision.
        # E.g., using instrument_details.precision.amount and instrument_details.limits.amount

        # Crossover logic
        # Golden Cross (Buy Signal): Short SMA crosses above Long SMA
        if prev_short_sma <= prev_long_sma and current_short_sma > current_long_sma:
            if is_short: # If currently short, close short and then go long
                signals.append({
                    "action": SignalAction.CLOSE_POSITION, "symbol": symbol, "comment": "Closing short due to golden cross.",
                    "amount": abs(current_position_amount), "order_type": "market", "strategy_name": self.strategy_key
                }) 
                # Bot executor would need to handle this by placing an opposite market order
            if not is_long: # Only open long if not already long
                signals.append({
                    "action": SignalAction.BUY, "symbol": symbol, "order_type": "market", "amount": order_amount,
                    "comment": f"Golden cross: Short SMA ({current_short_sma:.2f}) crossed above Long SMA ({current_long_sma:.2f}).",
                    "strategy_name": self.strategy_key
                })
            else:
                signals.append({"action": SignalAction.HOLD, "symbol": symbol, "comment": "Golden cross, but already long.", "strategy_name": self.strategy_key})
        
        # Death Cross (Sell Signal): Short SMA crosses below Long SMA
        elif prev_short_sma >= prev_long_sma and current_short_sma < current_long_sma:
            if is_long: # If currently long, close long and then go short (if shorting is intended)
                signals.append({
                    "action": SignalAction.CLOSE_POSITION, "symbol": symbol, "comment": "Closing long due to death cross.",
                    "amount": abs(current_position_amount), "order_type": "market", "strategy_name": self.strategy_key
                })
            # Example: This strategy only closes longs on death cross, doesn't open shorts.
            # To open shorts, add similar logic as for BUY:
            # if not is_short:
            #     signals.append({"action": SignalAction.SELL, ...})
            # else:
            signals.append({"action": SignalAction.HOLD, "symbol": symbol, "comment": "Death cross. Position might be closed. Holding further action.", "strategy_name": self.strategy_key})
        
        else:
            signals.append({"action": SignalAction.HOLD, "symbol": symbol, "comment": "No crossover.", "strategy_name": self.strategy_key})
            
        return signals