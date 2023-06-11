import pygame
import requests
import pandas as pd
import numpy as np
import asyncio
from datetime import datetime
from speechmanager import SpeechManager


class TechnicalAnalysisTool:
    def __init__(self):
        self.assets = []
        self.selected_asset = None
        self.ohlc_data = None
        self.chart = []
        self.current_series_index = 0
        self.current_row = 0
        self.current_column = 0
        self.step = 60  # in seconds
        self.timeframe_multiplier = 0
        self.interval = 1
        self.tts = SpeechManager()
        self.timeframes = ['Minute', 'Hour', 'Day', 'Week']

    async def run(self):
        pygame.init()
        window_width, window_height = 800, 600
        window = pygame.display.set_mode((window_width, window_height))
        pygame.display.set_caption("Technical Analysis Tool")

        clock = pygame.time.Clock()

        self.retrieve_asset_pairs()
        await self.select_asset_pair()

        if self.selected_asset is not None:
            self.retrieve_ohlc_data()
            self.create_chart()

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_PAGEUP:
                        self.change_series(-1)
                    elif event.key == pygame.K_PAGEDOWN:
                        self.change_series(1)
                        if self.current_series_index == 1:
                            self.current_row = 0  # Reset row index when switching to candle series
                    elif event.key == pygame.K_RIGHT:
                        self.move_along_data(1)
                    elif event.key == pygame.K_LEFT:
                        self.move_along_data(-1)
                    elif event.key == pygame.K_F1:
                        self.change_timeframe()
                    elif event.key == pygame.K_F2:
                        # If the shift key is also being pressed
                        if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                            self.change_interval(-1)
                        else:
                            self.change_interval(1)
                    elif event.key == pygame.K_F3:
                        await self.select_asset_pair()
                    elif event.key == pygame.K_F4:
                        self.retrieve_ohlc_data()
                        self.create_chart()

            window.fill((0, 0, 0))
            pygame.display.update()
            clock.tick(60)

        pygame.quit()

    def retrieve_asset_pairs(self):
        response = requests.get("https://www.bitstamp.net/api/v2/trading-pairs-info/")
        if response.status_code == 200:
            asset_pairs = response.json()
            self.assets = [pair["name"] for pair in asset_pairs]

    async def select_asset_pair(self):
        selected_asset = await self.show_menu(self.assets, "Select Asset Pair")
        if selected_asset:
            self.selected_asset = selected_asset.replace("/", "").lower()
            self.tts.speak(f"Selected asset pair: {self.selected_asset}")
            pygame.time.wait(1000)

    async def show_menu(self, options, title):
        selected_option = 0
        self.tts.speak(title)

        clock = pygame.time.Clock()

        while True:
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_UP:
                        selected_option = (selected_option - 1) % len(options)
                        self.tts.speak(options[selected_option])
                    elif event.key == pygame.K_DOWN:
                        selected_option = (selected_option + 1) % len(options)
                        self.tts.speak(options[selected_option])
                    elif event.key == pygame.K_RETURN:
                        self.tts.speak(f"Selected: {options[selected_option]}")
                        return options[selected_option]

            pygame.event.clear()
            clock.tick(60)

    def retrieve_ohlc_data(self):
        url = f"https://www.bitstamp.net/api/v2/ohlc/{self.selected_asset}/?step={self.step * self.interval}&limit=1000"
        response = requests.get(url)
        if response.status_code == 200:
            ohlc_data = response.json()
            if "data" in ohlc_data and "ohlc" in ohlc_data["data"]:
                data = ohlc_data["data"]["ohlc"]
                columns = ["timestamp", "high", "open", "close", "low", "volume"]
                self.ohlc_data = pd.DataFrame(data, columns=columns)
                self.tts.speak(f"Loaded {self.timeframes[self.timeframe_multiplier]} chart for {self.selected_asset}")
            else:
                self.tts.speak("No data available for that time interval.")
        else:
            self.tts.speak("No data available for that time interval.")

    def create_chart(self):
        if self.ohlc_data is not None:
            volume_series = np.array(self.ohlc_data["volume"])
            candles_series = np.array(self.ohlc_data[["high", "open", "close", "low"]])
            price_series = np.array(self.ohlc_data["close"])

            self.chart = [volume_series, candles_series, price_series]

            self.current_column = self.chart[self.current_series_index].shape[1] - 1 if len(
                self.chart[self.current_series_index].shape) > 1 else len(self.chart[self.current_series_index]) - 1

            # Adjust bounds checking for candle series
            if self.current_series_index == 1:
                self.current_column = min(self.current_column, len(self.chart[self.current_series_index][0]) - 1)
                self.current_row = min(self.current_row, len(self.chart[self.current_series_index]) - 1)

            self.tts.speak(self.get_series_name(self.current_series_index))
            self.tts.speak(self.get_current_data())

    def get_series_name(self, series_index):
        series_names = ["Volume", "Candles", "Price"]
        if 0 <= series_index < len(series_names):
            return series_names[series_index]
        else:
            return ""

    def get_current_data(self):
        if self.chart:
            series_name = self.get_series_name(self.current_series_index)
            timestamp = int(self.ohlc_data['timestamp'][self.current_column])  # Convert to integer

            if series_name == "Candles":
                row_headers = ["Open", "High", "Low", "Close"]
                values = [f"{header}: {value}" for header, value in zip(row_headers, self.chart[self.current_series_index][self.current_column])]
                values_str = ", ".join(values)
            else:
                value = self.chart[self.current_series_index][self.current_column]
                values_str = str(value)

            timestamp_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')  # Convert to readable format
            return f"{timestamp_str}, {series_name}, {values_str}"
        else:
            return "No data loaded"

    def change_series(self, direction):
        if self.chart:
            self.current_series_index = (self.current_series_index + direction) % len(self.chart)
            self.tts.speak(self.get_series_name(self.current_series_index))

    def move_along_data(self, direction):
        if self.chart:
            new_column = self.current_column + direction
            if 0 <= new_column < len(self.chart[self.current_series_index]):
                self.current_column = new_column
                self.tts.speak(self.get_current_data())

    def move_between_rows(self, direction):
        if self.chart and self.current_series_index == 1:  # Candle series
            new_row = self.current_row + direction
            if 0 <= new_row < len(self.chart[self.current_series_index]):
                self.current_row = new_row
                self.tts.speak(self.get_current_data())

    def change_timeframe(self):
        self.timeframe_multiplier = (self.timeframe_multiplier + 1) % len(self.timeframes)
        self.tts.speak(f"Timeframe changed to {self.timeframes[self.timeframe_multiplier]}")

    def change_interval(self, direction):
        self.interval = max(1, self.interval + direction)
        self.tts.speak(f"Interval changed to {self.interval}")


if __name__ == "__main__":
    tool = TechnicalAnalysisTool()
    asyncio.run(tool.run())
