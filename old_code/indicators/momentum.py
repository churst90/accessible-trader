import pandas as pd
from .indicator_base import IndicatorBase

class MomentumIndicator(IndicatorBase):
    def __init__(self, data_frame, **kwargs):
        super().__init__(data_frame, **kwargs)

        # General settings
        self.settings = {
            'momentum_period': 14,
            'smoothing_period': 1,
            'show_zero_line': True
        }

        # Appearance settings
        self.appearance_settings = {
            'line_thickness': '2',
            'positive_color': '#00FF00',  # Green
            'negative_color': '#FF0000',  # Red
            'zero_line_color': '#FFFFFF',  # White
            'zero_line_thickness': '1',
            'zero_line_style': 'dashed'
        }

        # Speech settings
        self.speech_settings = {
            'read_column_names': True,  # Whether to announce column names
            'read_order': ['timestamp', 'Momentum']  # Order in which to read columns
        }

        # Sound settings
        self.sound_settings = {
            'enable_sounds': True,  # Whether to enable sounds for events
            'sound_file': None  # Path to custom sound file (if any)
        }

    def is_overlay(self):
        return False  # Momentum is typically not an overlay

    def calculate(self):
        period = self.settings.get('momentum_period', 14)
        smoothing_period = self.settings.get('smoothing_period', 1)
        
        self.df['Momentum'] = self.df['close'].diff(period)

        if smoothing_period > 1:
            self.df['Momentum'] = self.df['Momentum'].rolling(window=smoothing_period).mean()

        # Attach appearance settings to the DataFrame
        self.df.attrs.update(self.appearance_settings)

        # Attach plot metadata
        self.df.attrs['plot_type'] = 'line'

        return self.df[['timestamp', 'Momentum']]

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
