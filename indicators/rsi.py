import pandas as pd
from .indicator_base import IndicatorBase
from event_bus import EventBus

class RSIIndicator(IndicatorBase):
    """Indicator for calculating the Relative Strength Index (RSI)."""

    def __init__(self, data_frame, **kwargs):
        # Initialize the base class with the relevant configuration section
        super().__init__(data_frame, name="RSI", config_section="rsi", **kwargs)

    def calculate(self):
        """Calculate the RSI based on the settings."""
        period = self.settings.get('period', 14)
        source_price = self.settings.get('source_price', 'close')
        smoothing = self.settings.get('signal_smoothing', 1)
        overbought_threshold = self.settings.get('overbought_threshold', 70)
        oversold_threshold = self.settings.get('oversold_threshold', 30)
        show_zones = self.settings.get('show_zones', True)

        # Calculate the price changes
        delta = self.df[source_price].diff()

        # Separate gains and losses
        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)

        # Calculate the average gain and loss
        avg_gain = gain.rolling(window=period, min_periods=1).mean()
        avg_loss = loss.rolling(window=period, min_periods=1).mean()

        # Apply smoothing if required
        if smoothing > 1:
            avg_gain = avg_gain.rolling(window=smoothing).mean()
            avg_loss = avg_loss.rolling(window=smoothing).mean()

        # Calculate the relative strength (RS) and RSI
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        self.df['RSI'] = rsi

        # Attach appearance settings to the DataFrame
        self.df.attrs.update(self.appearance_settings)

        # Attach plot metadata
        self.df.attrs['plot_type'] = 'line'
        self.df.attrs['overbought_threshold'] = overbought_threshold
        self.df.attrs['oversold_threshold'] = oversold_threshold
        self.df.attrs['show_zones'] = show_zones

        # Cache the result for reuse
        self.cache_result('rsi_data', self.df[['timestamp', 'RSI']])
        
        # Notify the event bus that the indicator has been recalculated
        event_bus.publish(f"{self.name}_recalculated")

        return self.df[['timestamp', 'RSI']]

    def is_overlay(self):
        """Return whether the indicator is an overlay on the primary chart axis."""
        return False  # RSI is typically not an overlay

    def get_audio_representation(self):
        """Return the audio representation of the RSI data."""
        rsi_values = self.get_cached_result('rsi_data')['RSI'].values
        audio_representation = {
            'values': rsi_values,
            'indicator_name': self.name
        }
        return audio_representation
