import pandas as pd
from .indicator_base import IndicatorBase

class MACDIndicator(IndicatorBase):
    def __init__(self, data_frame, **kwargs):
        super().__init__(data_frame, **kwargs)
        
        # General settings for MACD
        self.settings = {
            'fast_period': 12,  # Fast EMA period
            'slow_period': 26,  # Slow EMA period
            'signal_period': 9  # Signal line EMA period
        }
        
        # Appearance settings for MACD line, Signal line, and Histogram
        self.appearance_settings = {
            'macd_line': {'line_thickness': '2', 'line_color': '#0000FF'},  # Blue
            'signal_line': {'line_thickness': '2', 'line_color': '#FFA500'},  # Orange
            'histogram': {
                'positive_bar_color': '#00FF00',  # Green
                'negative_bar_color': '#FF0000',  # Red
                'bar_thickness': '1'
            }
        }

        # Speech settings
        self.speech_settings = {
            'read_column_names': True,  # Whether to announce column names
            'read_order': ['timestamp', 'MACD', 'Signal', 'Histogram']  # Order in which to read columns
        }

        # Sound settings
        self.sound_settings = {
            'enable_sounds': True,  # Whether to enable sounds for events
            'sound_file': None  # Path to custom sound file (if any)
        }

    def is_overlay(self):
        return False  # MACD is typically not an overlay

    def calculate(self):
        # Calculate the MACD line, Signal line, and Histogram
        self.df['MACD'] = self.df['close'].ewm(span=self.settings['fast_period'], adjust=False).mean() - \
                          self.df['close'].ewm(span=self.settings['slow_period'], adjust=False).mean()
        self.df['Signal'] = self.df['MACD'].ewm(span=self.settings['signal_period'], adjust=False).mean()
        self.df['Histogram'] = self.df['MACD'] - self.df['Signal']

        # Attach appearance settings to the DataFrame
        self.df.attrs['plot_type'] = 'histogram'
        self.df.attrs.update(self.appearance_settings['histogram'])

        # Attach line colors and thickness to the DataFrame for MACD and Signal lines
        self.df.attrs['macd_line_color'] = self.appearance_settings['macd_line']['line_color']
        self.df.attrs['signal_line_color'] = self.appearance_settings['signal_line']['line_color']
        self.df.attrs['macd_line_thickness'] = int(self.appearance_settings['macd_line']['line_thickness'])
        self.df.attrs['signal_line_thickness'] = int(self.appearance_settings['signal_line']['line_thickness'])

        # Return the DataFrame with the necessary columns for charting
        return self.df[['timestamp', 'MACD', 'Signal', 'Histogram']]

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
