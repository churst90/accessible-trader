import pandas as pd
from .indicator_base import IndicatorBase

class RSIIndicator(IndicatorBase):
    def __init__(self, data_frame, **kwargs):
        super().__init__(data_frame, **kwargs)

        # General settings
        self.settings = {
            'period': 14,
            'overbought_threshold': 70,
            'oversold_threshold': 30,
            'source_price': 'close',
            'signal_smoothing': 1,
            'show_zones': True
        }

        # Appearance settings
        self.appearance_settings = {
            'line_thickness': '2',
            'line_color': '#800080',  # Purple
            'overbought_color': '#FF0000',  # Red
            'oversold_color': '#008000',  # Green
            'zone_thickness': '1',
            'zone_style': 'dashed'
        }

        # Speech settings
        self.speech_settings = {
            'read_column_names': True,  # Whether to announce column names
            'read_order': ['timestamp', 'RSI']  # Order in which to read columns
        }

        # Sound settings
        self.sound_settings = {
            'enable_sounds': True,  # Whether to enable sounds for events
            'sound_file': None  # Path to custom sound file (if any)
        }

    def is_overlay(self):
        return False  # RSI is typically not an overlay

    def calculate(self):
        period = self.settings.get('period', 14)
        source_price = self.settings.get('source_price', 'close')
        smoothing = self.settings.get('signal_smoothing', 1)

        delta = self.df[source_price].diff()

        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)

        avg_gain = gain.rolling(window=period, min_periods=1).mean()
        avg_loss = loss.rolling(window=period, min_periods=1).mean()

        if smoothing > 1:
            avg_gain = avg_gain.rolling(window=smoothing).mean()
            avg_loss = avg_loss.rolling(window=smoothing).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        self.df['RSI'] = rsi

        # Attach appearance settings to the DataFrame
        self.df.attrs.update(self.appearance_settings)

        # Attach plot metadata
        self.df.attrs['plot_type'] = 'line'
        self.df.attrs['overbought_threshold'] = self.settings.get('overbought_threshold', 70)
        self.df.attrs['oversold_threshold'] = self.settings.get('oversold_threshold', 30)
        self.df.attrs['show_zones'] = self.settings.get('show_zones', True)

        # Return the DataFrame with timestamp and RSI columns for charting
        return self.df[['timestamp', 'RSI']]

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
