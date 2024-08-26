import pandas as pd
import matplotlib.pyplot as plt
import tkinter as tk
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class MatplotlibManager:
    def __init__(self, parent):
        # Create the figure and primary axis with a black background
        self.fig, self.primary_ax = plt.subplots(1, 1, facecolor='black')
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.fig.patch.set_facecolor('black')  # Set figure background to black

    def clear_plot(self):
        """Clear the current plot."""
        self.fig.clear()  # Clear the entire figure, including all axes
        self.primary_ax = self.fig.add_subplot(111, facecolor='black')  # Recreate the primary axis after clearing

    def draw_plot(self):
        """Draw the plot on the canvas."""
        self.canvas.draw()

    def create_secondary_axis(self, num_subplots, idx, sharex_with_primary=True):
        """Create and return a secondary axis for non-overlay indicators."""
        if sharex_with_primary:
            return self.fig.add_subplot(num_subplots, 1, idx, sharex=self.primary_ax, facecolor='black')
        else:
            return self.fig.add_subplot(num_subplots, 1, idx, facecolor='black')

    def plot_data(self, ax, df, label=None):
        if df is None:
            return

        # Print the DataFrame attributes to check appearance settings
        print("DataFrame Attributes (Appearance Settings):")
        print(df.attrs)

        plot_type = df.attrs.get('plot_type', 'line')

        df.iloc[:, 1] = df.iloc[:, 1].where(np.abs(df.iloc[:, 1]) > 1e-6, 0)

        if plot_type == 'line':
            color = df.attrs.get('line_color', 'white')
            thickness = int(df.attrs.get('line_thickness', 2))
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
        try:
            # Ensure x_data is numeric if it's datetime
            if pd.api.types.is_datetime64_any_dtype(x_data):
                x_data = x_data.astype('int64')  # Convert datetime to int (nanoseconds since epoch)

            # Check for invalid data in y_data
            if y_data.isnull().any() or not np.isfinite(y_data).all():
                print("Invalid data in y_data detected. Skipping this plot.")
                return

            # Ensure label is passed
            if label is None:
                label = 'Data Series'  # Default label if none provided

            ax.plot(x_data, y_data, color=color, linewidth=thickness, label=label)
            ax.set_facecolor('black')
        
        except Exception as e:
            print(f"Error plotting line: {e}")

    def plot_bars(self, ax, x_data, y_data, positive_color='green', negative_color='red', thickness=0.1, label=None):
        """Plot bars (histogram) on the given axis."""
        try:
            # Ensure x_data is numeric if it's datetime
            if pd.api.types.is_datetime64_any_dtype(x_data):
                x_data = x_data.astype('int64')  # Convert datetime to int (nanoseconds since epoch)

            # Ensure y_data is numeric
            if not np.issubdtype(y_data.dtype, np.number):
                print(f"Non-numeric data detected in y_data: {y_data}. Skipping this plot.")
                return

            # Check for invalid data in y_data
            if y_data.isnull().any() or not np.isfinite(y_data).all():
                print(f"Invalid data in y_data detected: {y_data}. Skipping this plot.")
                return

            # Filter out very small values (close to zero)
            y_data = y_data.where(np.abs(y_data) > 1e-6, 0)

            positive_values = y_data.where(y_data > 0, 0)
            negative_values = y_data.where(y_data <= 0, 0)

            # Ensure positive and negative values are numeric and valid
            if not np.issubdtype(positive_values.dtype, np.number) or not np.isfinite(positive_values).all():
                print(f"Invalid positive values detected: {positive_values}. Skipping this plot.")
                return

            if not np.issubdtype(negative_values.dtype, np.number) or not np.isfinite(negative_values).all():
                print(f"Invalid negative values detected: {negative_values}. Skipping this plot.")
                return

            # Skip plotting if data is effectively flat
            if positive_values.sum() == 0 and negative_values.sum() == 0:
                print("No significant data to plot (all values are zero). Skipping this plot.")
                return

            # Plot bars with positive and negative values
            ax.bar(x_data, positive_values, color=positive_color, width=thickness, label=label)
            ax.bar(x_data, negative_values, color=negative_color, width=thickness, label=label)
            ax.set_facecolor('black')

        except Exception as e:
            print(f"Error plotting bars: {e}")

    def plot_candlesticks(self, ax, data, bullish_color='green', bearish_color='red', wick_color='white', wick_thickness=1, candle_thickness=2):
        """Plot candlestick data on the given axis."""
        try:
            # Ensure x_data is numeric if it's datetime
            x_data = data['timestamp']
            if pd.api.types.is_datetime64_any_dtype(x_data):
                x_data = x_data.astype('int64')  # Convert datetime to int (nanoseconds since epoch)

            for i in range(len(data)):
                open_price = data['Open'].iloc[i]
                close_price = data['Close'].iloc[i]
                high_price = data['High'].iloc[i]
                low_price = data['Low'].iloc[i]
                color = bullish_color if close_price >= open_price else bearish_color
                ax.vlines(x=x_data.iloc[i], ymin=low_price, ymax=high_price, color=wick_color, linewidth=wick_thickness)
                ax.vlines(x=x_data.iloc[i], ymin=min(open_price, close_price), ymax=max(open_price, close_price), color=color, linewidth=candle_thickness)
            ax.set_facecolor('black')

        except Exception as e:
            print(f"Error plotting candlesticks: {e}")

    def add_legend(self, ax):
        handles, labels = ax.get_legend_handles_labels()
        print(f"Handles: {handles}, Labels: {labels}")  # Debugging print to check labels
        if handles and labels:
            ax.legend(loc='upper left', facecolor='black', edgecolor='white', labelcolor='white')
        else:
            print("No labeled artists found; skipping legend.")
