import pandas as pd

class IndicatorBase:
    def __init__(self, data_frame, **kwargs):
        self.df = data_frame
        self.settings = kwargs
        self.appearance_settings = {}  # Add appearance settings dictionary
        self.speech_settings = {
            'read_column_names': True,
            'read_order': list(data_frame.columns)  # Default order is the order of columns in the DataFrame
        }
        self.audio_representation = {}

    def update_speech_settings(self, **kwargs):
        self.speech_settings.update(kwargs)

    def get_speech_settings(self):
        return self.speech_settings

    def update_settings(self, **kwargs):
        self.settings.update(kwargs)

    def update_appearance_settings(self, **kwargs):
        self.appearance_settings.update(kwargs)

    def calculate(self, *args, **kwargs):
        raise NotImplementedError("Calculate method must be implemented by subclasses.")

    def get_settings(self):
        return self.settings

    def get_appearance_settings(self):
        return self.appearance_settings  # New method to retrieve appearance settings

    def get_audio_representation(self):
        return self.audio_representation
