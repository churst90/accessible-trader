import asyncio
import tkinter as tk
from utils import bind_focus_events, bind_key_navigation_events, subscribe_to_events

class ChartManager:
    def __init__(self, parent, event_bus, matplotlib_manager, accessibility_manager, indicator_manager):
        self.parent = parent
        self.event_bus = event_bus
        self.matplotlib_manager = matplotlib_manager
        self.accessibility_manager = accessibility_manager
        self.indicator_manager = indicator_manager

        # Create the canvas where the chart will be drawn
        self.canvas = tk.Canvas(self.parent, bg="darkblue")
        self.canvas.grid(row=0, column=0, sticky="nsew")

        # Initialize series and datapoint indexes
        self.series_names = []  # List of available series names
        self.chart_series = {}  # Dictionary of series data
        self.current_series_index = 0  # Index of the currently selected series
        self.current_datapoint_index = 0  # Index of the current data point in the series

        # Apply accessibility features to the canvas
        self.accessibility_manager.apply_accessibility_features(self.canvas)

        # Bind navigation keys for the chart using the utility
        self.bind_chart_navigation_keys()

        # Subscribe to necessary events
        self.subscribe_to_chart_events()

    def subscribe_to_chart_events(self):
        """
        Subscribe to events related to chart updates and data fetching using the centralized utility.
        """
        event_subscriptions = {
            "data_fetched": self.on_data_fetched,
            "chart_updated": self.announce_current_series
        }

        subscribe_to_events(self.event_bus, event_subscriptions)

    def bind_chart_navigation_keys(self):
        """
        Bind chart navigation keys to the canvas using the centralized utility.
        """
        navigation_map = {
            "<Left>": "previous_datapoint",
            "<Right>": "next_datapoint",
            "<Up>": "previous_column",
            "<Down>": "next_column",
            "<Prior>": "previous_series",
            "<Next>": "next_series",
            "<Home>": "first_datapoint_visible",
            "<End>": "last_datapoint_visible"
        }

        bind_key_navigation_events(self.canvas, self.handle_chart_key_action, navigation_map)

    async def handle_chart_key_action(self, action_name):
        """Handle chart key actions and announce them."""
        action_messages = {
            "previous_datapoint": "Moved to the previous data point.",
            "next_datapoint": "Moved to the next data point.",
            "previous_column": "Moved to the previous column.",
            "next_column": "Moved to the next column.",
            "previous_series": "Moved to the previous series.",
            "next_series": "Moved to the next series.",
            "first_datapoint_visible": "Moved to the first visible data point.",
            "last_datapoint_visible": "Moved to the last visible data point."
        }

        message = action_messages.get(action_name, "Unknown action.")
        self.accessibility_manager.speak(message)
        await self.event_bus.publish("key_action", action_name)

    async def on_data_fetched(self, df):
        """
        Handle the 'data_fetched' event by updating the chart with the fetched data.
        
        :param df: A DataFrame containing the fetched data.
        """
        if df.empty:
            await self.event_bus.publish("announce_speech", "No data available for the selected pair.")
            return

        # Update the chart with the fetched data
        await self.update_chart({'Price': (df, True)})

        await self.event_bus.publish("announce_speech", "Chart updated with the new data.")

    async def update_chart(self, series_data_dict):
        """
        Update the chart with new series data asynchronously.
        
        :param series_data_dict: A dictionary where the key is the series name and 
                                 the value is a tuple (DataFrame, is_overlay).
        """
        for name, (df, is_overlay) in series_data_dict.items():
            self.chart_series[name] = (df, is_overlay)
            if name not in self.series_names:
                self.series_names.append(name)

        await self.replot_chart()
        await self.event_bus.publish("chart_updated", len(self.chart_series))

    async def replot_chart(self):
        """
        Replot the chart with all active series asynchronously.
        """
        self.matplotlib_manager.clear_plot()  # Clear the plot using MatplotlibManager

        # Loop through the series and plot them
        for name, (df, is_overlay) in self.chart_series.items():
            self.matplotlib_manager.plot_data(self.matplotlib_manager.primary_ax, df, label=name)

        self.matplotlib_manager.draw_plot()  # Redraw the plot

    async def announce_current_series(self):
        """
        Announce the current series and data point.
        This method will provide accessible information for the user about the current state of the chart.
        """
        current_series = self.get_current_series()

        if current_series is not None:
            # Assuming you have some method to get the data for the current data point
            data_point = current_series.iloc[self.current_datapoint_index]
            series_name = self.series_names[self.current_series_index]

            # Announce the data point using the accessibility manager
            message = f"Series: {series_name}, Data: {data_point}"
            await self.event_bus.publish("announce_speech", message)
        else:
            await self.event_bus.publish("announce_speech", "No data available for announcement.")

    def get_current_series(self):
        """
        Retrieve the current series being viewed on the chart.
        This method should return the currently selected data series.
        """
        if self.series_names and self.current_series_index < len(self.series_names):
            return self.chart_series[self.series_names[self.current_series_index]][0]
        return None
