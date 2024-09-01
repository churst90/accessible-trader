import pandas as pd
from .indicator_base import IndicatorBase
from event_bus import EventBus

class MomentumIndicator(IndicatorBase):
    """Indicator for calculating the Momentum."""

    def __init__(self, data_frame, **kwargs):
        # Initialize the base class with the relevant configuration section
        super().__init__(data_frame, name="Momentum", config_section="momentum", **kwargs)

    def calculate(self):
        """Calculate the Momentum based on the settings."""
        period = self.settings.get('momentum_period', 14)
        smoothing_period = self.settings.get('smoothing_period', 1)
        show_zero_line = self.settings.get('show_zero_line', True)

        # Calculate the Momentum
        self.df['Momentum'] = self.df['close'].diff(period)

        # Apply smoothing if required
        if smoothing_period > 1:
            self.df['Momentum'] = self.df['Momentum'].rolling(window=smoothing_period).mean()

        # Attach appearance settings to the DataFrame
        self.df.attrs.update(self.appearance_settings)

        # Attach plot metadata
        self.df.attrs['plot_type'] = 'line'
        self.df.attrs['show_zero_line'] = show_zero_line

        # Cache the result for reuse
        self.cache_result('momentum_data', self.df[['timestamp', 'Momentum']])
        
        # Notify the event bus that the indicator has been recalculated
        event_bus.publish(f"{self.name}_recalculated")

        return self.df[['timestamp', 'Momentum']]

    def is_overlay(self):
        """Return whether the indicator is an overlay on the primary chart axis."""
        return False  # Momentum is typically not an overlay

    def get_audio_representation(self):
        """Return the audio representation of the Momentum data."""
        momentum_values = self.get_cached_result('momentum_data')['Momentum'].values
        audio_representation = {
            'values': momentum_values,
            'indicator_name': self.name
        }
        return audio_representation
