import tkinter as tk
import platform  # Import platform module
from concurrent.futures import ThreadPoolExecutor
import asyncio
import pandas as pd
from ui_components import UIComponents
from chart_manager import ChartManager
from accessibility import SpeechManager, KeyboardManager
from sound import AudioPresenter
from indicators.price import PriceIndicator
from indicators.candles import CandlestickIndicator
from indicators.macd import MACDIndicator
from indicators.rsi import RSIIndicator
from indicators.momentum import MomentumIndicator
from CryptoDataFetcher import CryptoDataFetcher
from graphics_manager import MatplotlibManager

class MainApplication(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Accessible Trader")
        self.geometry("3200x2400")
        self.configure(bg="black")

        # Instantiate managers
        self.matplotlib_manager = MatplotlibManager(self)
        self.speech_manager = SpeechManager()
        self.indicators = {}  # Store all indicators by name
        self.chart_manager = ChartManager(self, self.speech_manager, self.indicators, self.matplotlib_manager)
        self.keyboard_manager = KeyboardManager(self.chart_manager, self.speech_manager)
        self.ui_components = UIComponents(self, self.speech_manager)

        # Create the update button
        self.update_button = self.ui_components.create_button(self, "Update Chart", self.update_chart)

        # Style controls and layout them horizontally
        self.style_controls()

        # Bind keyboard navigation
        self.keyboard_manager.bind_keys(self.chart_manager.canvas.get_tk_widget())

        # Create ThreadPoolExecutor for background tasks
        self.executor = ThreadPoolExecutor(max_workers=2)

        # Handle application close event
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.raw_ohlcv_data = pd.DataFrame()  # Store the raw OHLCV data
        self.current_datapoint_index = 0  # Index to track the current datapoint

        # Initialize the AudioPresenter
        self.audio_presenter = AudioPresenter(audio_representation={}, custom_sounds_dir=None)

        # Auto-refresh setup
        self.auto_refresh = True
        self.refresh_interval = 60000  # Default to 1 minute

    def style_controls(self):
        """Style the main window controls with white text and black background."""
        self.ui_components.market_dropdown.config(background="black", foreground="white")
        self.ui_components.exchange_dropdown.config(background="black", foreground="white")
        self.ui_components.asset_dropdown.config(background="black", foreground="white")
        self.ui_components.multiplier_entry.config(background="black", foreground="white")
        self.ui_components.timeframe_dropdown.config(background="black", foreground="white")

        # Arrange controls horizontally
        controls_frame = tk.Frame(self, bg="black")
        controls_frame.pack(fill=tk.X, pady=10)
        self.ui_components.market_dropdown.pack(side=tk.LEFT, padx=5)
        self.ui_components.exchange_dropdown.pack(side=tk.LEFT, padx=5)
        self.ui_components.asset_dropdown.pack(side=tk.LEFT, padx=5)
        self.ui_components.multiplier_entry.pack(side=tk.LEFT, padx=5)
        self.ui_components.timeframe_dropdown.pack(side=tk.LEFT, padx=5)
        self.update_button.pack(side=tk.LEFT, padx=5)  # Now correctly references the update_button

    def load_exchanges(self):
        exchanges = CryptoDataFetcher.get_exchanges()
        self.ui_components.set_dropdown_values("exchange", exchanges)
        self.ui_components.exchange_dropdown.bind("<<ComboboxSelected>>", self.load_symbols)

    def load_symbols(self, event):
        exchange_id = self.ui_components.exchange_dropdown.get()
        if exchange_id:
            data_fetcher = CryptoDataFetcher(exchange_id)
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self.async_load_symbols(data_fetcher))

    async def async_load_symbols(self, data_fetcher):
        async with data_fetcher.exchange_session() as exchange:
            symbols = exchange.symbols
            self.ui_components.set_dropdown_values("asset", symbols)

    def register_indicator(self, name, indicator_class, *args, **kwargs):
        """Register an indicator and add it to the list of indicators."""
        indicator = indicator_class(self.raw_ohlcv_data, *args, **kwargs)
        self.indicators[name] = indicator
        refined_data = indicator.calculate()
        return refined_data

    def plot_all_indicators(self):
        """Plot all registered indicators."""
        self.chart_manager.plot_all_indicators()

    async def fetch_and_update_chart(self, exchange_id, symbol, timeframe):
        data_fetcher = CryptoDataFetcher(exchange_id)
        async with data_fetcher.exchange_session() as exchange:
            ohlcv_data = await data_fetcher.fetch_ohlcv_in_batches(symbol, timeframe, use_cache=False)

        if ohlcv_data.empty:
            self.speech_manager.speak("No data available for the selected pair.")
            return

        # Convert the OHLCV data to a DataFrame and rename columns
        self.raw_ohlcv_data = pd.DataFrame(ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # Convert timestamp to datetime for better readability (optional)
        self.raw_ohlcv_data['timestamp'] = pd.to_datetime(self.raw_ohlcv_data['timestamp'], unit='ms')

        # Register and calculate the Price indicator
        price_series = self.register_indicator('Price', PriceIndicator)
        candlestick_series = self.register_indicator('Candles', CandlestickIndicator)
        macd_series = self.register_indicator('MACD', MACDIndicator)
        rsi_series = self.register_indicator('RSI', RSIIndicator)
        momentum_series = self.register_indicator('Momentum', MomentumIndicator)

        # Update the chart manager with the series data and their overlay status
        self.chart_manager.update_chart({
            'Price': (price_series, True),  # Assuming Price is an overlay
            'Candles': (candlestick_series, True),
            'MACD': (macd_series, False),  # MACD requires its own axis
            'RSI': (rsi_series, False),    # RSI requires its own axis
            'Momentum': (momentum_series, False)  # Momentum requires its own axis
        })

        # Prepare the audio representation from all indicators
        self.prepare_audio_representation()

        self.speech_manager.speak(f"Chart loaded for {symbol}, {timeframe}. Chart has {len(self.indicators)} visible series.")

    def prepare_audio_representation(self):
        for name, indicator in self.indicators.items():
            self.audio_presenter.audio_representation[name] = indicator.get_audio_representation()

    def update_chart(self):
        exchange_id = self.ui_components.exchange_dropdown.get()
        symbol = self.ui_components.asset_dropdown.get()
        multiplier = self.ui_components.multiplier_entry.get()
        timeframe_unit = self.ui_components.timeframe_dropdown.get()

        if not exchange_id or not symbol or not multiplier or not timeframe_unit:
            self.speech_manager.speak("Please select an exchange, asset pair, multiplier, and timeframe.")
            return

        timeframe = f"{multiplier}{timeframe_unit[0]}"

        asyncio.run(self.fetch_and_update_chart(exchange_id, symbol, timeframe))
        self.set_auto_refresh(int(multiplier), timeframe_unit)

    def set_auto_refresh(self, multiplier, timeframe_unit):
        if timeframe_unit == "minute":
            self.refresh_interval = multiplier * 60 * 1000
        elif timeframe_unit == "hour":
            self.refresh_interval = multiplier * 60 * 60 * 1000
        elif timeframe_unit == "day":
            self.refresh_interval = multiplier * 24 * 60 * 60 * 1000
        else:
            self.refresh_interval = 60000

        if self.auto_refresh:
            self.after_cancel(self.auto_refresh)
        self.auto_refresh = self.after(self.refresh_interval, self.update_chart)

    def on_closing(self):
        if self.auto_refresh:
            self.after_cancel(self.auto_refresh)
        self.executor.shutdown(wait=False)
        self.audio_presenter.stop_audio()
        self.destroy()

if __name__ == "__main__":
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = MainApplication()
    app.mainloop()
