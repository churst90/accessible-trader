from accessible_output2.outputs.auto import Auto
import pandas as pd

class SpeechManager:
    def __init__(self):
        self.speech = Auto()

    def speak(self, message):
        if isinstance(message, (int, float)):
            message = str(message)
        elif not isinstance(message, str):
            message = repr(message)
        print(f"Speaking: {message}")
        self.speech.speak(message)

    def announce_key_action(self, action):
        """Announce key actions such as switching series or moving data points."""
        self.speak(action)

    def announce_chart_data(self, data, speech_settings):
        """Announce data based on speech settings."""
        if isinstance(data, pd.Series):
            # Read column names and values in the specified order
            for column_name in speech_settings.get('read_order', data.index):
                if column_name in data.index:
                    value = data[column_name]
                    if speech_settings.get('read_column_names', True):
                        self.speak(f"{column_name}: {value}")
                    else:
                        self.speak(f"{value}")
        elif isinstance(data, dict):
            # If it's a dictionary, iterate through the key-value pairs
            for key, value in data.items():
                if speech_settings.get('read_column_names', True):
                    self.speak(f"{key}: {value}")
                else:
                    self.speak(f"{value}")

class KeyboardManager:
    def __init__(self, chart_manager, speech_manager):
        self.chart_manager = chart_manager
        self.speech_manager = speech_manager

    def bind_keys(self, canvas):
        """Bind the keys to the chart area for keyboard navigation."""
        canvas.bind("<Prior>", self.previous_series)  # Page Up
        canvas.bind("<Next>", self.next_series)  # Page Down
        canvas.bind("<Left>", self.previous_datapoint)  # Left Arrow
        canvas.bind("<Right>", self.next_datapoint)  # Right Arrow
        canvas.bind("<Home>", self.first_datapoint)  # Home key
        canvas.bind("<End>", self.last_datapoint)  # End key
        canvas.bind("<F12>", self.open_settings_dialog)  # Bind F12 to open settings dialog

    def previous_series(self, event):
        """Navigate to the previous series in the chart."""
        self.chart_manager.previous_series()
        self.speech_manager.announce_key_action("Switched to previous series")

    def next_series(self, event):
        """Navigate to the next series in the chart."""
        self.chart_manager.next_series()
        self.speech_manager.announce_key_action("Switched to next series")

    def previous_datapoint(self, event):
        """Navigate to the previous data point within the current series."""
        if self.chart_manager.has_valid_series():
            self.chart_manager.previous_datapoint()
            self.chart_manager.announce_current_series()
        else:
            self.speech_manager.speak("No data available to navigate.")

    def next_datapoint(self, event):
        """Navigate to the next data point within the current series."""
        if self.chart_manager.has_valid_series():
            self.chart_manager.next_datapoint()
            self.chart_manager.announce_current_series()
        else:
            self.speech_manager.speak("No data available to navigate.")

    def first_datapoint(self, event):
        """Navigate to the first data point within the current series."""
        self.chart_manager.first_datapoint()
        self.speech_manager.announce_key_action("Moved to first data point")

    def last_datapoint(self, event):
        """Navigate to the last data point within the current series."""
        self.chart_manager.last_datapoint()
        self.speech_manager.announce_key_action("Moved to last data point")

    def open_settings_dialog(self, event):
        """Open the settings dialog for the currently focused series."""
        self.chart_manager.open_settings_dialog()
