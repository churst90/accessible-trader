import pandas as pd
from .indicator_base import IndicatorBase
from event_bus import EventBus

class CandlestickIndicator(IndicatorBase):
    """Indicator for plotting candlestick charts, including optional Heikin Ashi and pattern recognition."""

    def __init__(self, data_frame, **kwargs):
        # Initialize the base class with the relevant configuration section
        super().__init__(data_frame, name="Candles", config_section="candles", **kwargs)

    def calculate(self):
        """Calculate candlestick data for plotting, including optional Heikin Ashi and pattern recognition."""
        use_heikin_ashi = self.settings.get('use_heikin_ashi', False)
        recognize_patterns = self.settings.get('recognize_patterns', True)

        if use_heikin_ashi:
            # Calculate Heikin Ashi candlesticks
            self.df['HA_Close'] = (self.df['open'] + self.df['high'] + self.df['low'] + self.df['close']) / 4
            self.df['HA_Open'] = (self.df['open'].shift(1) + self.df['close'].shift(1)) / 2
            self.df['HA_High'] = self.df[['high', 'HA_Open', 'HA_Close']].max(axis=1)
            self.df['HA_Low'] = self.df[['low', 'HA_Open', 'HA_Close']].min(axis=1)
            self.df['Open'] = self.df['HA_Open']
            self.df['Close'] = self.df['HA_Close']
            self.df['High'] = self.df['HA_High']
            self.df['Low'] = self.df['HA_Low']
        else:
            # Use regular OHLC data
            self.df['Open'] = self.df['open']
            self.df['Close'] = self.df['close']
            self.df['High'] = self.df['high']
            self.df['Low'] = self.df['low']

        if recognize_patterns:
            # Identify basic candlestick patterns
            self.df['Pattern'] = self.identify_patterns()
        else:
            self.df['Pattern'] = None

        # Attach appearance settings to the DataFrame
        self.df.attrs.update(self.appearance_settings)

        # Attach plot metadata
        self.df.attrs['plot_type'] = 'candlestick'

        # Cache the result for reuse
        self.cache_result('candlestick_data', self.df[['timestamp', 'Open', 'High', 'Low', 'Close', 'Pattern']])
        
        # Notify the event bus that the indicator has been recalculated
        event_bus.publish(f"{self.name}_recalculated")

        return self.df[['timestamp', 'Open', 'High', 'Low', 'Close', 'Pattern']]

    def identify_patterns(self):
        """Identify simple candlestick patterns."""
        patterns = []
        for i in range(len(self.df)):
            pattern = None
            if self.df['Close'].iloc[i] > self.df['Open'].iloc[i]:
                pattern = 'Bullish'
            elif self.df['Close'].iloc[i] < self.df['Open'].iloc[i]:
                pattern = 'Bearish'
            patterns.append(pattern)
        return patterns

    def is_overlay(self):
        """Return whether the indicator is an overlay on the primary chart axis."""
        return True  # Candlesticks are typically overlaid on the primary axis (e.g., price)

    def get_audio_representation(self):
        """Return the audio representation of the candlestick data."""
        open_values = self.get_cached_result('candlestick_data')['Open'].values
        close_values = self.get_cached_result('candlestick_data')['Close'].values
        audio_representation = {
            'open_values': open_values,
            'close_values': close_values,
            'indicator_name': self.name
        }
        return audio_representation
