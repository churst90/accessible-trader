class IndicatorManager:
    def __init__(self, event_bus, config_manager):
        print("IndicatorManager: Initializing...")
        self.event_bus = event_bus
        self.config_manager = config_manager

        # Subscribe to relevant events from the EventBus
        self.event_bus.subscribe("settings_updated", self.on_settings_updated)

    def on_settings_updated(self, settings):
        """Handle updates when settings are changed."""
        print(f"IndicatorManager: Settings updated with: {settings}")
        # Handle the settings update logic here
        pass
