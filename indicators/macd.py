import pandas as pd
from .indicator_base import IndicatorBase
from event_bus import EventBus

class MACDIndicator(IndicatorBase):
    """Indicator for calculating the MACD (Moving Average Convergence Divergence)."""

    def __init__(self, data_frame, **kwargs):
        # Initialize the base class with the relevant configuration section
        super().__init__(data_frame, name="MACD", config_section="macd", **kwargs)

    def calculate(self):
        """Calculate the MACD, Signal line, and Histogram based on the settings."""
        fast_period = self.settings.get('fast_period', 12)
        slow_period = self.settings.get('slow_period', 26)
        signal_period = self.settings.get('signal_period', 9)

        # Calculate the MACD line
        self.df['MACD'] = self.df['close'].ewm(span=fast_period, adjust=False).mean() - \
                          self.df['close'].ewm(span=slow_period, adjust=False).mean()
        
        # Calculate the Signal line
        self.df['Signal'] = self.df['MACD'].ewm(span=signal_period, adjust=False).mean()

        # Calculate the Histogram
        self.df['Histogram'] = self.df['MACD'] - self.df['Signal']

        # Attach appearance settings to the DataFrame
        self.df.attrs.update(self.appearance_settings)

        # Attach plot metadata
        self.df.attrs['plot_type'] = 'histogram'

        # Cache the result for reuse
        self.cache_result('macd_data', self.df[['timestamp', 'MACD', 'Signal', 'Histogram']])
        
        # Notify the event bus that the indicator has been recalculated
        event_bus.publish(f"{self.name}_recalculated")

        return self.df[['timestamp', 'MACD', 'Signal', 'Histogram']]

    def is_overlay(self):
        """Return whether the indicator is an overlay on the primary chart axis."""
        return False  # MACD is typically not an overlay

    def get_audio_representation(self):
        """Return the audio representation of the MACD data."""
        macd_values = self.get_cached_result('macd_data')['MACD'].values
        signal_values = self.get_cached_result('macd_data')['Signal'].values
        histogram_values = self.get_cached_result('macd_data')['Histogram'].values
        audio_representation = {
            'macd_values': macd_values,
            'signal_values': signal_values,
            'histogram_values': histogram_values,
            'indicator_name': self.name
        }
        return audio_representation
