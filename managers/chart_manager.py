import asyncio
import tkinter as tk

class ChartManager:
    def __init__(self, parent, event_bus, matplotlib_manager, accessibility_manager, indicator_manager):
        print("ChartManager: Initializing...")
        self.parent = parent
        self.event_bus = event_bus
        self.matplotlib_manager = matplotlib_manager
        self.accessibility_manager = accessibility_manager
        self.indicator_manager = indicator_manager

        # Initialize series and datapoint indexes
        self.series_names = []
        self.current_series_index = 0
        self.current_datapoint_index = 0
        self.chart_series = {}

        # Create the canvas where the chart will be drawn
        self.canvas = tk.Canvas(self.parent, bg="darkblue")
        self.canvas.grid(row=0, column=0, sticky="nsew")

        # Configure the canvas to take focus
        self.canvas.configure(takefocus=True)

        # Apply accessibility features to the canvas
        self.accessibility_manager.apply_accessibility_features(self.canvas)

        # Ensure the grid layout expands with the window
        self.parent.grid_rowconfigure(0, weight=1)
        self.parent.grid_columnconfigure(0, weight=1)

        # Add the canvas to the Matplotlib figure
        self.fig, self.ax = self.matplotlib_manager.fig, self.matplotlib_manager.primary_ax
        self.fig.set_canvas(self.canvas)

        # Bind chart navigation keys to the canvas
        self.accessibility_manager.bind_chart_keys(self.canvas)

        # Subscribe to necessary events
        self.subscribe_to_events()

    def subscribe_to_events(self):
        """Subscribe to events from the EventBus."""
        print("ChartManager: Subscribing to events...")
        self.event_bus.subscribe("data_fetched", self.on_data_fetched)
        self.event_bus.subscribe("chart_updated", self.announce_current_series)

    async def on_data_fetched(self, df):
        """Handle the 'data_fetched' event by updating the chart with the fetched data."""
        print("ChartManager: Data fetched...")
        if df.empty:
            await self.event_bus.publish("announce_speech", "No data available for the selected pair.")
            return

        # Update the chart manager with the series data and their overlay status
        await self.update_chart({
            'Price': (df, True),
        })

        await self.event_bus.publish("announce_speech", "Chart updated with the new data.")

    async def update_chart(self, series_data_dict):
        """Update the chart with new series data asynchronously."""
        print("ChartManager: Updating chart...")
        for name, (df, is_overlay) in series_data_dict.items():
            self.chart_series[name] = (df, is_overlay)
            if name not in self.series_names:
                self.series_names.append(name)
        await self.replot_chart()
        await self.event_bus.publish("chart_updated", len(self.chart_series))

    async def replot_chart(self):
        """Replot the chart with all active indicators asynchronously."""
        print("ChartManager: Replotting chart...")
        self.matplotlib_manager.clear_plot()  # Clear the plot using MatplotlibManager
        axes = []

        # Plot each indicator managed by IndicatorManager
        for indicator in self.indicator_manager.get_all_indicators():
            df = indicator.calculate()
            if indicator.is_overlay():
                ax = self.matplotlib_manager.primary_ax
            else:
                ax = self.matplotlib_manager.create_secondary_axis(len(self.chart_series) + 1, len(axes) + 2)
            self.matplotlib_manager.plot_data(ax, df, label=indicator.name)
            axes.append(ax)

        # Adjust the layout to avoid overlap
        self.matplotlib_manager.draw_plot()

    def get_current_series(self):
        """Retrieve the currently selected series."""
        print("ChartManager: Getting current series...")
        if self.has_valid_series():
            current_series_name = self.series_names[self.current_series_index]
            return self.chart_series[current_series_name][0]
        return None

    def has_valid_series(self):
        """Check if the current series index is valid."""
        print("ChartManager: Checking for valid series...")
        return len(self.series_names) > 0 and self.current_series_index < len(self.series_names)

    async def announce_current_series(self):
        """Announce the data for the current series and data point asynchronously."""
        print("ChartManager: Announcing current series...")
        current_series = self.get_current_series()
        if current_series is not None:
            data = current_series.iloc[self.current_datapoint_index]
            current_series_name = self.series_names[self.current_series_index]
            await self.event_bus.publish("announce_speech", f"{current_series_name} series, Data: {data}")

    async def previous_series(self):
        """Navigate to the previous series in the chart asynchronously."""
        print("ChartManager: Moving to previous series...")
        if self.series_names:
            self.current_series_index = (self.current_series_index - 1) % len(self.series_names)
            await self.announce_current_series()

    async def next_series(self):
        """Navigate to the next series in the chart asynchronously."""
        print("ChartManager: Moving to next series...")
        if self.series_names:
            self.current_series_index = (self.current_series_index + 1) % len(self.series_names)
            await self.announce_current_series()

    async def previous_datapoint(self):
        """Navigate to the previous data point within the current series asynchronously."""
        print("ChartManager: Moving to previous data point...")
        if self.has_valid_series():
            self.current_datapoint_index = max(0, self.current_datapoint_index - 1)
            await self.announce_current_series()
        else:
            await self.event_bus.publish("announce_speech", "No data available to navigate.")

    async def next_datapoint(self):
        """Navigate to the next data point within the current series asynchronously."""
        print("ChartManager: Moving to next data point...")
        if self.has_valid_series():
            self.current_datapoint_index = min(len(self.get_current_series().iloc[:, 0]) - 1, self.current_datapoint_index + 1)
            await self.announce_current_series()
        else:
            await self.event_bus.publish("announce_speech", "No data available to navigate.")

    async def first_datapoint(self):
        """Navigate to the first data point within the current series asynchronously."""
        print("ChartManager: Moving to first data point...")
        if self.has_valid_series():
            self.current_datapoint_index = 0
            await self.announce_current_series()

    async def last_datapoint(self):
        """Navigate to the last data point within the current series asynchronously."""
        print("ChartManager: Moving to last data point...")
        if self.has_valid_series():
            self.current_datapoint_index = len(self.get_current_series().iloc[:, 0]) - 1
            await self.announce_current_series()

    async def open_settings_dialog(self):
        """Open the settings dialog asynchronously."""
        print("ChartManager: Opening settings dialog...")
        await self.event_bus.publish("announce_speech", "Settings dialog opened.")
        # You would add code here to actually open the settings dialog if it exists
