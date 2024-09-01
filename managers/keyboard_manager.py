import asyncio

class KeyboardManager:
    def __init__(self, event_bus, accessibility_manager):
        self.event_bus = event_bus
        self.accessibility_manager = accessibility_manager

    def bind_keys(self, widget):
        """Bind global keys for navigation."""
        widget.bind("<Prior>", self.wrap_key_event("previous_series"))  # Page Up
        widget.bind("<Next>", self.wrap_key_event("next_series"))  # Page Down
        widget.bind("<Left>", self.wrap_key_event("previous_datapoint"))  # Left Arrow
        widget.bind("<Right>", self.wrap_key_event("next_datapoint"))  # Right Arrow
        widget.bind("<Home>", self.wrap_key_event("first_datapoint"))  # Home key
        widget.bind("<End>", self.wrap_key_event("last_datapoint"))  # End key
        widget.bind("<F12>", self.wrap_key_event("open_settings_dialog"))  # Bind F12 to open settings dialog

    def wrap_key_event(self, action_name):
        """Wrap key event to handle async functions."""
        async def handler(event):
            await self.event_bus.publish("key_action", action_name)
            action_method = getattr(self.accessibility_manager, action_name, None)
            if action_method:
                await action_method()
            else:
                print(f"No method found for action: {action_name}")
        return lambda event: asyncio.run(handler(event))

    def bind_chart_keys(self, canvas):
        """Bind keys specifically for chart navigation when focus is on the chart area."""
        self.bind_keys(canvas)
