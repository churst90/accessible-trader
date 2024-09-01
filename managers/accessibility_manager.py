import asyncio
import tkinter as tk
from tkinter import ttk
from accessible_output2.outputs.auto import Auto

class AccessibilityManager:
    def __init__(self, event_bus):
        print("AccessibilityManager: Initializing...")
        self.event_bus = event_bus
        self.speech = Auto()
        self.speech_enabled = True
        self.subscribe_to_events()

    def subscribe_to_events(self):
        print("AccessibilityManager: Subscribing to events...")
        """Subscribe to relevant events from the EventBus."""
        try:
            self.event_bus.subscribe("announce_speech", self.handle_speech)
            self.event_bus.subscribe("chart_updated", self.handle_chart_update)
            self.event_bus.subscribe("data_fetched", self.handle_data_fetched)
            self.event_bus.subscribe("error_occurred", self.handle_error)
        except Exception as e:
            print(f"AccessibilityManager: Error during subscription - {e}")

    def handle_speech(self, message):
        print(f"AccessibilityManager: handle_speech method called with message: {message}")
        """Handle speech output events."""
        try:
            if self.speech_enabled:
                self.speak(message)
        except Exception as e:
            print(f"AccessibilityManager: Error in handle_speech - {e}")

    def handle_chart_update(self, series_count):
        print(f"AccessibilityManager: handle_chart_update method called with series_count: {series_count}")
        """Handle chart update events."""
        try:
            self.speak(f"Chart updated with {series_count} series.")
        except Exception as e:
            print(f"AccessibilityManager: Error in handle_chart_update - {e}")

    def handle_data_fetched(self, message):
        print(f"AccessibilityManager: handle_data_fetched method called with message: {message}")
        """Handle data fetched events."""
        try:
            self.speak(f"Data fetched: {message}")
        except Exception as e:
            print(f"AccessibilityManager: Error in handle_data_fetched - {e}")

    def handle_error(self, error_message):
        print(f"AccessibilityManager: handle_error method called with error_message: {error_message}")
        """Handle error events."""
        try:
            self.speak(f"Error: {error_message}")
        except Exception as e:
            print(f"AccessibilityManager: Error in handle_error - {e}")

    def speak(self, message):
        print(f"AccessibilityManager: speak method called with message: {message}")
        """Safely handle the speaking of messages."""
        try:
            if isinstance(message, (int, float)):
                message = str(message)
            elif not isinstance(message, str):
                message = repr(message)
            
            self.speech.speak(message)
        except Exception as e:
            print(f"AccessibilityManager: Error in speak method - {e}")

    def announce_widget(self, widget):
        print("AccessibilityManager: announce_widget method called")
        """Announce the focused widget."""
        try:
            label_text = None
            widget_value = ""
            control_type = widget.winfo_class()

            # Explicitly handle combobox to ensure correct announcement
            if isinstance(widget, ttk.Combobox):
                control_type = "combobox"
                widget_value = widget.get()
                self.bind_combobox_navigation(widget)  # Bind navigation for combobox
            elif isinstance(widget, ttk.Entry):
                control_type = "edit box"
                widget_value = widget.get()
            elif isinstance(widget, ttk.Checkbutton):
                control_type = "checkbox"
                widget_value = "checked" if widget.instate(['selected']) else "unchecked"
            elif isinstance(widget, ttk.Radiobutton):
                control_type = "radiobutton"
                widget_value = widget.cget("text")
            elif isinstance(widget, ttk.Scale):
                control_type = "slider"
                widget_value = widget.get()
            elif isinstance(widget, ttk.Button):
                control_type = "button"
                widget_value = widget.cget("text")
            elif isinstance(widget, tk.Canvas):
                control_type = "chart area"
                widget_value = ""  # No need to say "Focus is on the chart area"

            # Look for a label associated with the widget
            master = widget.master
            while master is not None:
                if hasattr(master, 'label_widget_mapping'):
                    label_text = master.label_widget_mapping.get(widget)
                    break
                master = master.master

            if label_text:
                message = f"{label_text}, {control_type}, {widget_value}"
            else:
                message = f"{control_type}, {widget_value}"

            # Publish the message to the event bus to be spoken
            asyncio.run_coroutine_threadsafe(
                self.event_bus.publish("announce_speech", message),
                asyncio.get_event_loop()
            )
        except Exception as e:
            print(f"AccessibilityManager: Error in announce_widget method - {e}")

    def bind_focus_change(self, widget):
        print(f"AccessibilityManager: bind_focus_change method called for widget: {widget}")
        """Bind focus change events to announce when a widget gains focus."""
        try:
            widget.bind("<FocusIn>", self.on_focus_in)
        except Exception as e:
            print(f"AccessibilityManager: Error in bind_focus_change method - {e}")

    def on_focus_in(self, event):
        print(f"AccessibilityManager: on_focus_in method called for event: {event}")
        """Handle the focus-in event and announce the focused widget."""
        try:
            focused_widget = event.widget
            self.announce_widget(focused_widget)
        except Exception as e:
            print(f"AccessibilityManager: Error in on_focus_in method - {e}")

    def bind_tab_navigation(self, widget):
        print(f"AccessibilityManager: bind_tab_navigation method called for widget: {widget}")
        """Bind Tab and Shift+Tab to navigate between fields in a dialog."""
        try:
            widget.bind("<Tab>", self.handle_tab_press)
            widget.bind("<Shift-Tab>", self.handle_shift_tab_press)
            for child in widget.winfo_children():
                self.bind_tab_navigation(child)
        except Exception as e:
            print(f"AccessibilityManager: Error in bind_tab_navigation method - {e}")

    def handle_tab_press(self, event):
        print(f"AccessibilityManager: handle_tab_press method called for event: {event}")
        """Handle Tab key press to move to the next widget and announce it."""
        try:
            current_widget = event.widget.focus_get()
            next_widget = current_widget.tk_focusNext()
            if next_widget:
                next_widget.focus_set()
                self.announce_widget(next_widget)
            return "break"
        except Exception as e:
            print(f"AccessibilityManager: Error in handle_tab_press method - {e}")

    def handle_shift_tab_press(self, event):
        print(f"AccessibilityManager: handle_shift_tab_press method called for event: {event}")
        """Handle Shift+Tab key press to move to the previous widget and announce it."""
        try:
            current_widget = event.widget.focus_get()
            prev_widget = current_widget.tk_focusPrev()
            if prev_widget:
                prev_widget.focus_set()
                self.announce_widget(prev_widget)
            return "break"
        except Exception as e:
            print(f"AccessibilityManager: Error in handle_shift_tab_press method - {e}")

    def apply_accessibility_features(self, widget):
        print(f"AccessibilityManager: apply_accessibility_features method called for widget: {widget}")
        """Apply focus change and tab navigation features to all children."""
        try:
            self.bind_focus_change(widget)
            self.bind_tab_navigation(widget)

            # Ensure Canvas can take focus
            if isinstance(widget, tk.Canvas):
                widget.configure(takefocus=True)
            
            for child in widget.winfo_children():
                self.apply_accessibility_features(child)
        except Exception as e:
            print(f"AccessibilityManager: Error in apply_accessibility_features method - {e}")

    def bind_combobox_navigation(self, combobox):
        """Bind the combobox navigation to announce selection changes."""
        combobox.bind("<Up>", self.on_combobox_navigation)
        combobox.bind("<Down>", self.on_combobox_navigation)
        combobox.bind("<<ComboboxSelected>>", self.on_combobox_navigation)

    def on_combobox_navigation(self, event):
        combobox = event.widget
        selection = combobox.get()
        self.speak(selection)

    def bind_chart_keys(self, canvas):
        """Bind chart navigation keys for the canvas."""
        print("AccessibilityManager: Binding chart navigation keys...")
        try:
            canvas.bind("<Left>", lambda e: self.handle_chart_key_action("previous_datapoint"))
            canvas.bind("<Right>", lambda e: self.handle_chart_key_action("next_datapoint"))
            canvas.bind("<Up>", lambda e: self.handle_chart_key_action("previous_column"))
            canvas.bind("<Down>", lambda e: self.handle_chart_key_action("next_column"))
            canvas.bind("<Prior>", lambda e: self.handle_chart_key_action("previous_series"))
            canvas.bind("<Next>", lambda e: self.handle_chart_key_action("next_series"))
            canvas.bind("<Home>", lambda e: self.handle_chart_key_action("first_datapoint_visible"))
            canvas.bind("<End>", lambda e: self.handle_chart_key_action("last_datapoint_visible"))
            canvas.bind("<F12>", lambda e: self.handle_chart_key_action("open_settings_dialog"))
        except Exception as e:
            print(f"AccessibilityManager: Error in bind_chart_keys method - {e}")

    def handle_chart_key_action(self, action_name):
        """Handle and announce chart key actions."""
        try:
            action_messages = {
                "previous_datapoint": "Moved to the previous data point.",
                "next_datapoint": "Moved to the next data point.",
                "previous_column": "Moved to the previous column.",
                "next_column": "Moved to the next column.",
                "previous_series": "Moved to the previous series.",
                "next_series": "Moved to the next series.",
                "first_datapoint_visible": "Moved to the first visible data point.",
                "last_datapoint_visible": "Moved to the last visible data point.",
                "open_settings_dialog": "Settings dialog opened."
            }
            message = action_messages.get(action_name, "Unknown action.")
            self.speak(message)
            asyncio.run_coroutine_threadsafe(
                self.event_bus.publish("key_action", action_name), asyncio.get_event_loop()
            )
        except Exception as e:
            print(f"AccessibilityManager: Error in handle_chart_key_action method - {e}")
