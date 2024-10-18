from utils import subscribe_to_events

class IndicatorManager:
    def __init__(self, event_bus, config_manager):
        self.event_bus = event_bus
        self.config_manager = config_manager

        # Subscribe to settings-related events using the centralized utility
        self.subscribe_to_indicator_events()

    def subscribe_to_indicator_events(self):
        """
        Subscribe to events related to indicator updates.
        """
        event_subscriptions = {
            "settings_updated": self.on_settings_updated
        }

        subscribe_to_events(self.event_bus, event_subscriptions)

    def on_settings_updated(self, settings):
        """Handle updates when settings are changed."""
        # Logic to handle settings updates...
        pass
