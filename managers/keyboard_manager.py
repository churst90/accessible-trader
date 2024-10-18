import asyncio
from utils import bind_key_navigation_events

class KeyboardManager:
    def __init__(self, event_bus, accessibility_manager):
        self.event_bus = event_bus
        self.accessibility_manager = accessibility_manager

    def bind_keys(self, widget):
        """
        Bind global keys for navigation on the given widget (e.g., chart or dialog).
        This function will use the centralized `bind_navigation_keys` utility function.
        """
        navigation_map = {
            "<Prior>": "previous_series",  # Page Up
            "<Next>": "next_series",       # Page Down
            "<Left>": "previous_datapoint",  # Left Arrow
            "<Right>": "next_datapoint",    # Right Arrow
            "<Home>": "first_datapoint",    # Home key
            "<End>": "last_datapoint",      # End key
            "<F12>": "open_settings_dialog"  # F12 key to open settings
        }

        # Use the utility function to bind keys to the widget
        bind_navigation_keys(widget, navigation_map, self.handle_key_action)

    def handle_key_action(self, action_name):
        """
        Handle the action triggered by a key press.
        Publishes the action to the event bus and performs any necessary tasks.
        """
        asyncio.run(self.event_bus.publish("key_action", action_name))
        action_method = getattr(self.accessibility_manager, action_name, None)
        if action_method:
            asyncio.run(action_method())
        else:
            print(f"No method found for action: {action_name}")
