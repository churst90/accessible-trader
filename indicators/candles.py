import pandas as pd
from .indicator_base import IndicatorBase

class CandlestickIndicator(IndicatorBase):
    def __init__(self, data_frame, **kwargs):
        super().__init__(data_frame, **kwargs)
        
        # General settings
        self.settings = {
            'use_heikin_ashi': False,  # Whether to use Heikin Ashi candles
            'recognize_patterns': True  # Whether to recognize candle patterns
        }
        
        # Appearance settings for candles and wicks
        self.appearance_settings = {
            'bullish_color': '#00FF00',  # Green for bullish candles
            'bearish_color': '#FF0000',  # Red for bearish candles
            'wick_color': '#FFFFFF',     # White for candle wicks
            'wick_thickness': '1',       # Thickness for candle wicks
            'candle_thickness': '2'      # Thickness for candle bodies
        }

        # Speech settings
        self.speech_settings = {
            'read_column_names': True,  # Whether to announce column names
            'read_order': ['timestamp', 'Open', 'High', 'Low', 'Close', 'Pattern']  # Order in which to read columns
        }

        # Sound settings
        self.sound_settings = {
            'enable_sounds': True,  # Whether to enable sounds for events
            'sound_file': None  # Path to custom sound file (if any)
        }

    def is_overlay(self):
        return True  # Candles are typically overlaid on the primary axis (e.g., price)

    def calculate(self):
        # Calculate either standard or Heikin Ashi candles
        if self.settings.get('use_heikin_ashi', False):
            self.df['Open'] = (self.df['open'].shift(1) + self.df['close'].shift(1)) / 2
            self.df['Close'] = (self.df['open'] + self.df['high'] + self.df['low'] + self.df['close']) / 4
            self.df['High'] = self.df[['high', 'Open', 'Close']].max(axis=1)
            self.df['Low'] = self.df[['low', 'Open', 'Close']].min(axis=1)
        else:
            self.df['Open'] = self.df['open']
            self.df['Close'] = self.df['close']
            self.df['High'] = self.df['high']
            self.df['Low'] = self.df['low']
        
        # Identify candle patterns (Bullish/Bearish)
        if self.settings.get('recognize_patterns', True):
            self.df['Pattern'] = self.identify_patterns()
        else:
            self.df['Pattern'] = None
        
        # Attach appearance settings to the DataFrame
        self.df.attrs.update(self.appearance_settings)

        # Attach plot metadata
        self.df.attrs['plot_type'] = 'candlestick'

        # Return the DataFrame with standardized column names
        return self.df[['timestamp', 'Open', 'High', 'Low', 'Close', 'Pattern']]

    def identify_patterns(self):
        patterns = []
        for i in range(len(self.df)):
            pattern = None
            if self.df['Close'].iloc[i] > self.df['Open'].iloc[i]:
                pattern = 'Bullish'
            elif self.df['Close'].iloc[i] < self.df['Open'].iloc[i]:
                pattern = 'Bearish'
            patterns.append(pattern)
        return patterns

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
