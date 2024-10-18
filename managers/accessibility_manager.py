import tkinter as tk
from tkinter import ttk
import asyncio
from accessible_output2.outputs.auto import Auto
from utils import bind_focus_events, bind_combobox_navigation_events

class AccessibilityManager:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.speech_enabled = True  # Example setting for speech output system
        self.speech = Auto()

        # Subscribe to necessary events
        self.subscribe_to_events()

    def subscribe_to_events(self):
        self.event_bus.subscribe("announce_speech", self.handle_speech)
        self.event_bus.subscribe("chart_updated", self.handle_chart_update)

    def handle_speech(self, message):
        """
        Handle speech output when the 'announce_speech' event is triggered.
        This method is called when an 'announce_speech' event is published.
        """
        if self.speech_enabled:
            self.speak(message)

    def handle_chart_update(self, series_count):
        """
        Handle chart updates and provide an announcement of the updated chart state.
        """
        self.speak(f"Chart updated with {series_count} series.")

    def speak(self, message):
        """Speak the message using the speech output system."""
        self.speech.speak(message)

    def bind_focus_change(self, widget):
        """Bind focus change events for accessibility."""
        bind_focus_events(self, widget)  # Use the utility function to bind focus events

    def bind_combobox_navigation(self, combobox):
        """Bind navigation events specific to Combobox widgets."""
        bind_combobox_navigation_events(self, combobox)  # Use the utility function for Combobox

    def on_focus_in(self, event):
        """Handle focus-in event and announce the focused widget."""
        focused_widget = event.widget
        self.announce_widget(focused_widget)

    def on_combobox_navigation(self, event):
        """Handle Combobox navigation (Up/Down arrow keys)."""
        combobox = event.widget
        current_selection = combobox.get()
        self.speak(f"Selected: {current_selection}")

    def on_combobox_selection(self, event):
        """Handle Combobox item selection."""
        combobox = event.widget
        current_selection = combobox.get()
        self.speak(f"Combobox selection changed to: {current_selection}")

    def apply_accessibility_features(self, widget):
        """
        Apply accessibility features to a widget, such as focus and key bindings.
        This can be used for canvases or other UI components that need accessibility support.
        """
        bind_focus_events(self, widget)

    def announce_widget(self, widget):
        """
        Announce the content or description of the focused widget.

        This method retrieves the content of the widget (like text or value),
        and speaks it using the accessibility system.
        """

        widget_type = widget.winfo_class()
    
        # Detect if the widget is a text entry (text field)
        if isinstance(widget, tk.Entry) or isinstance(widget, ttk.Entry):
            value = widget.get()
            if value:
                self.speak(f"Text field with value: {value}")
            else:
                self.speak("Empty text field")

        # Detect if the widget is a Combobox (dropdown)
        elif isinstance(widget, ttk.Combobox):
            selected = widget.get()
            if selected:
                self.speak(f"Combobox. Selected: {selected}")
            else:
                self.speak("Combobox. No selection")

            # Bind arrow key events to read selections in the dropdown
            widget.bind("<Down>", self.on_combobox_arrow_navigation)
            widget.bind("<Up>", self.on_combobox_arrow_navigation)

        # Detect if the widget is a Button
        elif isinstance(widget, tk.Button) or isinstance(widget, ttk.Button):
            button_text = widget.cget("text")
            if button_text:
                self.speak(f"Button: {button_text}")
            else:
                self.speak("Button with no label")

        # Detect if the widget is a Label
        elif isinstance(widget, tk.Label) or isinstance(widget, ttk.Label):
            label_text = widget.cget("text")
            if label_text:
                self.speak(f"Label: {label_text}")
            else:
                self.speak("Label with no text")

        # Detect if the widget is a Canvas (e.g., for charts)
        elif isinstance(widget, tk.Canvas):
            self.speak("Live chart area")

        else:
            # If not a recognized widget type, fall back to announcing the widget type
            self.speak(f"Widget: {widget_type}")

    def on_combobox_arrow_navigation(self, event):
        """
        Handle arrow key navigation in a Combobox and announce the current selection.
        This method will be triggered when you use the Up/Down keys to navigate through
        the Combobox items.
        """
        combobox = event.widget
        current_selection = combobox.get()
        if current_selection:
            self.speak(f"Selected: {current_selection}")
        else:
            self.speak("No selection")

    def on_combobox_selection(self, event):
        """
        Handle Combobox item selection (via Enter key or mouse click).
        Announce the newly selected item.
        """
        combobox = event.widget
        current_selection = combobox.get()
        if current_selection:
            self.speak(f"Combobox changed to: {current_selection}")
        else:
            self.speak("Combobox selection cleared")
