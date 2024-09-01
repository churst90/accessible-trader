import pandas as pd
from abc import ABC, abstractmethod
from config import config_manager
from event_bus import EventBus

class IndicatorBase(ABC):
    """Base class for all technical indicators."""
    
    def __init__(self, data_frame, name, config_section, **kwargs):
        self.df = data_frame
        self.name = name
        self.config_section = config_section
        self.settings = config_manager.get(config_section, {})
        self.appearance_settings = self.settings.get('appearance', {})
        self.speech_settings = self.settings.get('speech', {})
        self.sound_settings = self.settings.get('sound', {})
        self.event_subscriptions = []

        # Update settings with any provided keyword arguments
        self.settings.update(kwargs)

        # Cache for calculated values
        self.cache = {}

        # Subscribe to settings updates
        self.subscribe_to_settings_updates()

    @abstractmethod
    def calculate(self):
        """Calculate the indicator values based on the data."""
        pass

    def get_settings(self):
        """Return the current settings for the indicator."""
        return self.settings

    def update_settings(self, **kwargs):
        """Update the settings for the indicator and save them in the configuration."""
        self.settings.update(kwargs)
        config_manager.set(self.config_section, self.settings)

    def get_appearance_settings(self):
        """Return the appearance settings for the indicator."""
        return self.appearance_settings

    def update_appearance_settings(self, **kwargs):
        """Update the appearance settings for the indicator."""
        self.appearance_settings.update(kwargs)
        self.update_settings(appearance=self.appearance_settings)

    def get_speech_settings(self):
        """Return the speech settings for the indicator."""
        return self.speech_settings

    def update_speech_settings(self, **kwargs):
        """Update the speech settings for the indicator."""
        self.speech_settings.update(kwargs)
        self.update_settings(speech=self.speech_settings)

    def get_sound_settings(self):
        """Return the sound settings for the indicator."""
        return self.sound_settings

    def update_sound_settings(self, **kwargs):
        """Update the sound settings for the indicator."""
        self.sound_settings.update(kwargs)
        self.update_settings(sound=self.sound_settings)

    def cache_result(self, key, value):
        """Cache a calculated result for reuse."""
        self.cache[key] = value

    def get_cached_result(self, key):
        """Retrieve a cached result if it exists."""
        return self.cache.get(key)

    def subscribe_to_settings_updates(self):
        """Subscribe to settings updates and reapply them when they change."""
        subscription = event_bus.subscribe("settings_updated", self.on_settings_updated)
        self.event_subscriptions.append(subscription)

    def on_settings_updated(self):
        """Reapply settings when the configuration is updated."""
        self.settings = config_manager.get(self.config_section, {})
        self.appearance_settings = self.settings.get('appearance', {})
        self.speech_settings = self.settings.get('speech', {})
        self.sound_settings = self.settings.get('sound', {})
        self.recalculate_indicator()

    def recalculate_indicator(self):
        """Recalculate the indicator with the current settings."""
        self.cache.clear()  # Clear cached results
        self.calculate()

    def cleanup(self):
        """Cleanup any resources and unsubscribe from events."""
        for subscription in self.event_subscriptions:
            event_bus.unsubscribe(subscription)

    @abstractmethod
    def is_overlay(self):
        """Return whether the indicator is an overlay on the primary chart axis."""
        pass

    @abstractmethod
    def get_audio_representation(self):
        """Return the audio representation of the indicator data."""
        pass
