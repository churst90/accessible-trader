import pandas as pd
from .indicator_base import IndicatorBase
from event_bus import EventBus

class PriceIndicator(IndicatorBase):
    """Indicator for plotting price data on the primary chart axis."""

    def __init__(self, data_frame, **kwargs):
        # Initialize the base class with the relevant configuration section
        super().__init__(data_frame, name="Price", config_section="price", **kwargs)

    def calculate(self):
        """Calculate the price data for plotting."""
        price_source = self.settings.get('price_source', 'close')
        
        if price_source in self.df.columns:
            self.df['Price'] = self.df[price_source]
        else:
            raise ValueError(f"Invalid price type: {price_source}")

        # Cache the result for reuse
        self.cache_result('price_data', self.df[['timestamp', 'Price']])
        
        # Notify the event bus that the indicator has been recalculated
        event_bus.publish(f"{self.name}_recalculated")

        return self.df[['timestamp', 'Price']]

    def is_overlay(self):
        """Return whether the indicator is an overlay on the primary chart axis."""
        return True  # Price is typically plotted as an overlay

    def get_audio_representation(self):
        """Return the audio representation of the price data."""
        price_values = self.get_cached_result('price_data')['Price'].values
        audio_representation = {
            'values': price_values,
            'indicator_name': self.name
        }
        return audio_representation
