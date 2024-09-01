import tkinter as tk
from tkinter import ttk

class UIComponents:
    def __init__(self, parent, speech_manager):
        self.speech_manager = speech_manager

        # Market Dropdown
        market_frame = ttk.LabelFrame(parent, text="Market")
        market_frame.pack(pady=5)
        self.market_dropdown = ttk.Combobox(market_frame)
        self.market_dropdown.pack(pady=5)
        self.market_dropdown.bind("<FocusIn>", self.announce_dropdown("Market"))

        # Exchange Dropdown
        exchange_frame = ttk.LabelFrame(parent, text="Exchange")
        exchange_frame.pack(pady=5)
        self.exchange_dropdown = ttk.Combobox(exchange_frame)
        self.exchange_dropdown.pack(pady=5)
        self.exchange_dropdown.bind("<FocusIn>", self.announce_dropdown("Exchange"))

        # Asset Pair Dropdown
        asset_frame = ttk.LabelFrame(parent, text="Asset Pair")
        asset_frame.pack(pady=5)
        self.asset_dropdown = ttk.Combobox(asset_frame)
        self.asset_dropdown.pack(pady=5)
        self.asset_dropdown.bind("<FocusIn>", self.announce_dropdown("Asset Pair"))

        # Multiplier Entry
        multiplier_frame = ttk.LabelFrame(parent, text="Multiplier")
        multiplier_frame.pack(pady=5)
        self.multiplier_entry = tk.Entry(multiplier_frame)
        self.multiplier_entry.insert(0, "1")  # Default value
        self.multiplier_entry.pack(pady=5)
        self.multiplier_entry.bind("<FocusIn>", lambda event: self.speech_manager.speak(f"Multiplier entry: {self.multiplier_entry.get()}"))

        # Timeframe Dropdown
        timeframe_frame = ttk.LabelFrame(parent, text="Timeframe")
        timeframe_frame.pack(pady=5)
        self.timeframe_dropdown = ttk.Combobox(timeframe_frame, values=["minute", "hour", "day", "week", "month", "year"])
        if len(self.timeframe_dropdown['values']) > 0:
            self.timeframe_dropdown.current(0)  # Default to the first item
        self.timeframe_dropdown.pack(pady=5)
        self.timeframe_dropdown.bind("<FocusIn>", self.announce_dropdown("Timeframe"))

    def announce_dropdown(self, label):
        def _announce(event):
            selected_option = event.widget.get()
            self.speech_manager.speak(f"{label} dropdown. Selected: {selected_option}")
        return _announce

    def set_dropdown_values(self, dropdown_name, values):
        dropdown = getattr(self, f'{dropdown_name}_dropdown', None)
        if dropdown:
            dropdown['values'] = values
            if len(values) > 0:
                dropdown.current(0)  # Set the default selection to the first item

    def create_button(self, parent, label, command):
        button = tk.Button(parent, text=label, command=command)
        button.pack(pady=10)
        button.bind("<FocusIn>", lambda event: self.speech_manager.speak(f"{label} button"))
        return button
