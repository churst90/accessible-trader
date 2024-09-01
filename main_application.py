import asyncio
import platform
import tkinter as tk
from managers.config_manager import ConfigManager
from core.event_bus import EventBus
from managers.accessibility_manager import AccessibilityManager
from managers.chart_manager import ChartManager
from managers.matplotlib_manager import MatplotlibManager
from managers.keyboard_manager import KeyboardManager
from ui.dialog import Dialog
from data_fetchers.crypto_data_fetcher import CryptoDataFetcher
from managers.indicator_manager import IndicatorManager

class MainApplication(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Accessible Trader")
        self.geometry("2400x1800")
        self.configure(bg="black")

        # Initialize ConfigManager and EventBus
        self.config_manager = ConfigManager()
        self.event_bus = EventBus()

        # Initialize managers with dependency injection
        self.indicator_manager = IndicatorManager(self.event_bus, self.config_manager)
        self.accessibility_manager = AccessibilityManager(self.event_bus)
        self.matplotlib_manager = MatplotlibManager(self, self.config_manager)
        self.chart_manager = ChartManager(
            self, self.event_bus, self.matplotlib_manager, self.accessibility_manager, self.indicator_manager
        )
        self.keyboard_manager = KeyboardManager(self.event_bus, self.accessibility_manager)
        self.data_fetcher = CryptoDataFetcher(self.event_bus)

        # Set up the main dialog
        self.setup_main_dialog()

        # Start the event bus processing loop with a small delay to ensure the loop is running
        self.after(100, lambda: self.event_bus.start(asyncio.get_event_loop()))

        # Subscribe to events
        self.event_bus.subscribe("data_fetched", lambda df: asyncio.run_coroutine_threadsafe(self.on_data_fetched(df), self.async_loop))
        self.event_bus.subscribe("exchange_selected", lambda exchange: asyncio.run_coroutine_threadsafe(self.on_exchange_selected(exchange), self.async_loop))

        # Integrate asyncio loop with Tkinter's event loop
        self.async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.async_loop)
        self.after(200, self.process_events)

    def setup_main_dialog(self):
        fields_config = [
            {'name': 'market', 'label': 'Market', 'type': 'dropdown', 'values': ['crypto', 'indices', 'stocks', 'forex', 'commodities']},
            {'name': 'exchange', 'label': 'Exchange', 'type': 'dropdown', 'values': []},
            {'name': 'asset', 'label': 'Asset Pair', 'type': 'dropdown', 'values': []},
            {'name': 'multiplier', 'label': 'Multiplier', 'type': 'entry', 'default': '1'},
            {'name': 'timeframe', 'label': 'Timeframe', 'type': 'dropdown', 'values': ["minute", "hour", "day", "week", "month", "year"]}
        ]

        self.dialog_frame = Dialog(
            self, "Accessible Trader", fields_config, self.event_bus, self.accessibility_manager, is_toplevel=False
        )
        self.dialog_frame.grid(row=1, column=0, sticky="ew")

        # Add Update button
        self.dialog_frame.create_button("Update Chart", self.update_chart, row=0, column=0)

        # Bind selection change for the market dropdown to populate exchanges
        self.dialog_frame.fields['market'].bind("<<ComboboxSelected>>", self.on_market_selected)

        # Bind selection change for the exchange dropdown to populate asset pairs
        self.dialog_frame.fields['exchange'].bind("<<ComboboxSelected>>", self.on_exchange_selected)

        # Populate exchanges initially
        self.populate_exchanges()

    def process_events(self):
        """Process asyncio events in the Tkinter event loop."""
        try:
            self.async_loop.run_until_complete(asyncio.sleep(0.1))
        except Exception as e:
            print(f"Error in process_events: {e}")
        finally:
            self.after(100, self.process_events)  # Schedule the next event processing

    def populate_exchanges(self):
        exchanges = CryptoDataFetcher.get_exchanges()
        self.dialog_frame.fields['exchange']['values'] = exchanges

    async def on_market_selected(self, event):
        market = self.dialog_frame.fields['market'].get()
        if market == 'crypto':
            exchanges = CryptoDataFetcher.get_exchanges()
        else:
            exchanges = []  # Add logic for other markets as needed

        self.dialog_frame.fields['exchange']['values'] = exchanges
        self.dialog_frame.fields['exchange'].set('')  # Clear current selection
        self.accessibility_manager.speak("Exchanges list updated")

    async def on_exchange_selected(self, event):
        exchange_id = self.dialog_frame.fields['exchange'].get()
        if exchange_id:
            symbol_list = await self.data_fetcher.get_symbols_for_exchange(exchange_id)
            self.dialog_frame.fields['asset']['values'] = symbol_list
            self.dialog_frame.fields['asset'].set('')  # Clear current selection
            self.accessibility_manager.speak("Asset pairs list updated")

    def update_chart(self):
        asyncio.run_coroutine_threadsafe(self.async_update_chart(), self.async_loop)

    async def async_update_chart(self):
        exchange_id = self.dialog_frame.fields['exchange'].get()
        symbol = self.dialog_frame.fields['asset'].get()
        multiplier = self.dialog_frame.fields['multiplier'].get()
        timeframe_unit = self.dialog_frame.fields['timeframe'].get()

        if not exchange_id or not symbol or not multiplier or not timeframe_unit:
            await self.event_bus.async_publish(
                "announce_speech", "Please select an exchange, asset pair, multiplier, and timeframe."
            )
            return

        timeframe = f"{multiplier}{timeframe_unit[0]}"
        await self.event_bus.async_publish("fetch_data", exchange_id, symbol, timeframe)

    async def on_data_fetched(self, df):
        if df.empty:
            await self.event_bus.async_publish("announce_speech", "No data available for the selected pair.")
            return

        # Update the chart manager with the data
        await self.chart_manager.update_chart({
            'Price': (df, True),
        })

        await self.event_bus.async_publish("announce_speech", "Chart updated with the new data.")

    def on_closing(self):
        print("Closing application...")
        # Cancel all tasks before closing
        for task in asyncio.all_tasks(self.async_loop):
            print(f"Cancelling task: {task}")
            task.cancel()
        
        # Stop the event loop
        self.async_loop.call_soon_threadsafe(self.async_loop.stop)
        self.destroy()
        print("Application closed.")

if __name__ == "__main__":
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = MainApplication()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
