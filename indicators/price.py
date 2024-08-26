import pandas as pd
from .indicator_base import IndicatorBase

class PriceIndicator(IndicatorBase):
    def __init__(self, data_frame, **kwargs):
        super().__init__(data_frame, **kwargs)

        # General settings
        self.settings = {
            'price_source': 'close'  # Default to the closing price
        }

        # Appearance settings
        self.appearance_settings = {
            'line_thickness': '2',  # Thickness as a string for Entry widget
            'line_color': '#FFFFFF',  # Color as a string (white)
            'label': 'Price'  # Add a label for the price line
        }

        # Speech settings
        self.speech_settings = {
            'read_column_names': True,  # Whether to announce column names
            'read_order': ['timestamp', 'Price']  # Order in which to read columns
        }

        # Sound settings
        self.sound_settings = {
            'enable_sounds': True,  # Whether to enable sounds for events
            'sound_file': None  # Path to custom sound file (if any)
        }

    def is_overlay(self):
        return True  # Price is typically plotted as an overlay

    def calculate(self):
        price_type = self.settings.get('price_source', 'close')
        if price_type in self.df.columns:
            self.df['Price'] = self.df[price_type]
        else:
            raise ValueError(f"Invalid price type: {price_type}")

        # Attach appearance settings to the DataFrame
        self.df.attrs.update(self.appearance_settings)

        # Attach plot metadata
        self.df.attrs['plot_type'] = 'line'

        # Return the DataFrame with timestamp and Price columns for charting
        return self.df[['timestamp', 'Price']]

    # Speech settings methods
    def get_speech_settings(self):
        return self.speech_settings

    def set_speech_settings(self, new_speech_settings):
        self.speech_settings.update(new_speech_settings)

    # Sound settings methods
    def get_sound_settings(self):
        return self.sound_settings

    def set_sound_settings(self, new_sound_settings):
        self.sound_settings.update(new_sound_settings)
