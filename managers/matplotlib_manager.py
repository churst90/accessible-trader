import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import numpy as np
import tkinter as tk

class MatplotlibManager:
    def __init__(self, parent, config_manager):
        print("MatplotlibManager: Initializing...")
        self.config_manager = config_manager

        # Load appearance settings from ConfigManager
        self.bg_color = self.config_manager.get('appearance', {}).get('background_color', 'black')
        self.line_color = self.config_manager.get('appearance', {}).get('foreground_color', 'white')

        # Create the figure and primary axis with a background color from the config
        self.fig, self.primary_ax = plt.subplots(1, 1, facecolor=self.bg_color)
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)

        # Use grid for the canvas
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        self.fig.patch.set_facecolor(self.bg_color)  # Set figure background to config color

        # Create a separate frame for the toolbar
        toolbar_frame = tk.Frame(parent)
        toolbar_frame.grid(row=1, column=0, sticky="ew")

        # Add toolbar for Matplotlib using the pack method inside the frame
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
        self.toolbar.update()

        # Ensure Canvas can take focus
        self.canvas.get_tk_widget().configure(takefocus=True)
        
        # Bind focus event for accessibility
        parent.accessibility_manager.bind_focus_change(self.canvas.get_tk_widget())

    def clear_plot(self):
        """Clear the current plot."""
        print("MatplotlibManager: Clearing plot...")
        self.fig.clear()  # Clear the entire figure, including all axes
        self.primary_ax = self.fig.add_subplot(111, facecolor=self.bg_color)  # Recreate the primary axis after clearing

    def draw_plot(self):
        """Draw the plot on the canvas."""
        print("MatplotlibManager: Drawing plot...")
        try:
            self.canvas.draw()
        except Exception as e:
            print(f"Error drawing plot: {e}")

    def create_secondary_axis(self, num_subplots, idx, sharex_with_primary=True):
        """Create and return a secondary axis for non-overlay indicators."""
        print("MatplotlibManager: Creating secondary axis...")
        if sharex_with_primary:
            return self.fig.add_subplot(num_subplots, 1, idx, sharex=self.primary_ax, facecolor=self.bg_color)
        else:
            return self.fig.add_subplot(num_subplots, 1, idx, facecolor=self.bg_color)

    def plot_data(self, ax, df, label=None):
        print("MatplotlibManager: Plotting data...")
        if df is None:
            return

        plot_type = df.attrs.get('plot_type', 'line')

        # Clean up data: avoid tiny values that could clutter the chart
        df.iloc[:, 1] = df.iloc[:, 1].where(np.abs(df.iloc[:, 1]) > 1e-6, 0)

        if plot_type == 'line':
            color = df.attrs.get('line_color', self.line_color)
            thickness = int(df.attrs.get('line_thickness', self.config_manager.get('appearance', {}).get('line_thickness', 2)))
            label = label if label else df.attrs.get('label', 'Line')  # Default label if not provided
            self.plot_line(ax, df['timestamp'], df.iloc[:, 1], color=color, thickness=thickness, label=label)
        elif plot_type == 'candlestick':
            self.plot_candlesticks(ax, df,
                                   bullish_color=df.attrs.get('bullish_color', '#00FF00'),
                                   bearish_color=df.attrs.get('bearish_color', '#FF0000'),
                                   wick_color=df.attrs.get('wick_color', '#FFFFFF'),
                                   wick_thickness=int(df.attrs.get('wick_thickness', 1)),
                                   candle_thickness=int(df.attrs.get('candle_thickness', 2)))
        elif plot_type == 'histogram':
            label = df.attrs.get('label', 'Histogram')  # Default label if not provided
            self.plot_bars(ax, df['timestamp'], df['Histogram'],
                           positive_color=df.attrs.get('positive_bar_color', '#00FF00'),
                           negative_color=df.attrs.get('negative_bar_color', '#FF0000'),
                           thickness=float(df.attrs.get('bar_thickness', 0.1)),
                           label=label)

        self.add_legend(ax)

    def plot_line(self, ax, x_data, y_data, color='white', thickness=2, label=None):
        """Plot a line on the given axis."""
        print("MatplotlibManager: Plotting line...")
        try:
            ax.plot(x_data, y_data, color=color, linewidth=thickness, label=label)
            ax.set_facecolor(self.bg_color)  # Set the background color for the axis

        except Exception as e:
            print(f"Error plotting line: {e}")

    def plot_bars(self, ax, x_data, y_data, positive_color='green', negative_color='red', thickness=0.1, label=None):
        """Plot bars (histogram) on the given axis."""
        print("MatplotlibManager: Plotting bars...")
        try:
            positive_values = y_data.where(y_data > 0, 0)
            negative_values = y_data.where(y_data <= 0, 0)

            ax.bar(x_data, positive_values, color=positive_color, width=thickness, label=label)
            ax.bar(x_data, negative_values, color=negative_color, width=thickness, label=label)
            ax.set_facecolor(self.bg_color)

        except Exception as e:
            print(f"Error plotting bars: {e}")

    def plot_candlesticks(self, ax, data, bullish_color='green', bearish_color='red', wick_color='white', wick_thickness=1, candle_thickness=2):
        """Plot candlestick data on the given axis."""
        print("MatplotlibManager: Plotting candlesticks...")
        try:
            x_data = data['timestamp']

            for i in range(len(data)):
                open_price = data['Open'].iloc[i]
                close_price = data['Close'].iloc[i]
                high_price = data['High'].iloc[i]
                low_price = data['Low'].iloc[i]
                color = bullish_color if close_price >= open_price else bearish_color
                ax.vlines(x=x_data.iloc[i], ymin=low_price, ymax=high_price, color=wick_color, linewidth=wick_thickness)
                ax.vlines(x=x_data.iloc[i], ymin=min(open_price, close_price), ymax=max(open_price, close_price), color=color, linewidth=candle_thickness)
            ax.set_facecolor(self.bg_color)

        except Exception as e:
            print(f"Error plotting candlesticks: {e}")

    def add_legend(self, ax):
        print("MatplotlibManager: Adding legend...")
        handles, labels = ax.get_legend_handles_labels()
        if handles and labels:
            ax.legend(loc='upper left', facecolor=self.bg_color, edgecolor='white', labelcolor='white')
