import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class ChartManager:
    def __init__(self, parent, speech_manager, indicators, matplotlib_manager):
        self.speech_manager = speech_manager
        self.indicators = indicators  # Store the indicators dictionary
        self.matplotlib_manager = matplotlib_manager  # Handle the actual plotting

        # Create the initial subplot using matplotlib
        self.fig, self.ax = self.matplotlib_manager.fig, self.matplotlib_manager.primary_ax
        self.canvas = self.matplotlib_manager.canvas
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.get_tk_widget().bind("<FocusIn>", self.on_focus_chart_area)

        # Data structures to manage series and navigation
        self.chart_series = {}  # Dictionary to store series data for multiple indicators
        self.series_names = []
        self.current_series_index = 0  # Track current series index for navigation
        self.current_datapoint_index = 0  # Track current datapoint index within the series

    def on_focus_chart_area(self, event):
        self.speech_manager.speak("Live chart area.")

    def add_indicator(self, name, indicator_df, is_overlay):
        """Add a new indicator to the chart and update the layout."""
        self.chart_series[name] = (indicator_df, is_overlay)
        self.series_names.append(name)
        self.replot_chart()

    def remove_indicator(self, name):
        """Remove an indicator from the chart and update the layout."""
        if name in self.chart_series:
            del self.chart_series[name]
            self.series_names.remove(name)
            self.replot_chart()

    def replot_chart(self):
        """Replot the chart with all active indicators."""
        self.matplotlib_manager.clear_plot()  # Clear the plot using MatplotlibManager
        axes = []

        # Split indicators into overlay (for the primary axis) and separate axis indicators
        overlay_indicators = [name for name, (df, is_overlay) in self.chart_series.items() if is_overlay]
        separate_axes_indicators = [name for name, (df, is_overlay) in self.chart_series.items() if not is_overlay]

        # Create the primary axis for the price (and other overlay indicators)
        if overlay_indicators:
            self.primary_ax = self.ax  # Use the primary ax
            
            for series_name in overlay_indicators:
                df, _ = self.chart_series[series_name]
                label = df.attrs.get('label', series_name)  # Use the series name as a fallback label
                self.matplotlib_manager.plot_data(self.primary_ax, df, label)
                
            axes.append(self.primary_ax)

        # Create separate axes for indicators that require their own axis
        for idx, series_name in enumerate(separate_axes_indicators, start=2):
            ax = self.matplotlib_manager.create_secondary_axis(len(separate_axes_indicators) + 1, idx)
            df, _ = self.chart_series[series_name]
            label = df.attrs.get('label', series_name)  # Use the series name as a fallback label
            self.matplotlib_manager.plot_data(ax, df, label)
            axes.append(ax)

        # Adjust the layout to avoid overlap
        self.matplotlib_manager.draw_plot()

    def update_chart(self, series_data_dict):
        """Update the chart with new series data."""
        for name, (df, is_overlay) in series_data_dict.items():
            self.chart_series[name] = (df, is_overlay)
            if name not in self.series_names:
                self.series_names.append(name)
        self.replot_chart()
        self.speech_manager.speak(f"Chart updated with {len(self.chart_series)} series.")

    def clear_chart(self):
        """Clear the chart of all indicators."""
        self.chart_series.clear()
        self.series_names.clear()
        self.replot_chart()
        self.speech_manager.speak("Chart cleared.")

    def previous_series(self):
        """Navigate to the previous series in the chart."""
        if self.series_names:
            self.current_series_index = (self.current_series_index - 1) % len(self.series_names)
            self.announce_current_series()

    def next_series(self):
        """Navigate to the next series in the chart."""
        if self.series_names:
            self.current_series_index = (self.current_series_index + 1) % len(self.series_names)
            self.announce_current_series()

    def previous_datapoint(self):
        """Navigate to the previous data point within the current series."""
        if self.has_valid_series():
            self.current_datapoint_index = max(0, self.current_datapoint_index - 1)
            self.announce_current_series()

    def next_datapoint(self):
        """Navigate to the next data point within the current series."""
        if self.has_valid_series():
            self.current_datapoint_index = min(len(self.get_current_series().iloc[:, 0]) - 1, self.current_datapoint_index + 1)
            self.announce_current_series()

    def first_datapoint(self):
        """Navigate to the first data point within the current series."""
        if self.has_valid_series():
            self.current_datapoint_index = 0
            self.announce_current_series()

    def last_datapoint(self):
        """Navigate to the last data point within the current series."""
        if self.has_valid_series():
            self.current_datapoint_index = len(self.get_current_series().iloc[:, 0]) - 1
            self.announce_current_series()

    def get_current_series(self):
        """Retrieve the currently selected series."""
        if self.has_valid_series():
            current_series_name = self.series_names[self.current_series_index]
            return self.chart_series[current_series_name][0]
        return None

    def has_valid_series(self):
        """Check if the current series index is valid."""
        return len(self.series_names) > 0 and self.current_series_index < len(self.series_names)

    def announce_current_series(self):
        """Announce the data for the current series and data point."""
        current_series = self.get_current_series()
        if current_series is not None:
            data = current_series.iloc[self.current_datapoint_index]
            current_series_name = self.series_names[self.current_series_index]
            current_speech_settings = self.indicators[current_series_name].get_speech_settings()
            self.speech_manager.speak(f"Moved to {current_series_name} series.")
            self.speech_manager.announce_chart_data(data, current_speech_settings)

    def open_settings_dialog(self):
        """Open the settings dialog for the currently focused series."""
        current_series_name = self.series_names[self.current_series_index]
        current_indicator = self.indicators[current_series_name]
        SettingsDialog(self.canvas.get_tk_widget().master, current_indicator, self.speech_manager)
