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
                    elif event.key == pygame.K_DOWN:
                        self.move_between_rows(1)
                    elif event.key == pygame.K_UP:
                        self.move_between_rows(-1)
                    elif event.key == pygame.K_F1:
                        self.change_timeframe()
                    elif event.key == pygame.K_F2:
                        self.change_interval()
                    elif event.key == pygame.K_F3:
                        await self.select_asset_pair()
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
            else:
                print("No OHLC data returned from the server.")
        else:
            print(f"Error retrieving OHLC data: {response.status_code}")

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
            self.current_column = min(max(0, self.current_column), len(self.chart[self.current_series_index][0]) - 1)
            self.current_row = min(max(0, self.current_row), len(self.chart[self.current_series_index]) - 1)
            self.tts.speak(self.get_current_data())

    def move_along_data(self, direction):
        if self.chart:
            self.current_column = max(0, min(self.current_column + direction, len(self.chart[self.current_series_index][0]) - 1))
            self.tts.speak(self.get_current_data())
        else:
            self.tts.speak("No data loaded")

    def move_between_rows(self, direction):
        if self.chart and self.current_series_index == 1:
            self.current_row = max(0, min(self.current_row + direction, len(self.chart[self.current_series_index]) - 1))
            self.tts.speak(self.get_current_data())
        else:
            self.tts.speak("No candle series loaded")

    def change_timeframe(self):
        self.timeframe_multiplier = (self.timeframe_multiplier + 1) % len(self.timeframes)
        self.tts.speak(f"Current timeframe: {self.timeframes[self.timeframe_multiplier]}")
        self.step = 60 * (60 ** self.timeframe_multiplier)
        if self.selected_asset:
            self.retrieve_ohlc_data()
            self.create_chart()

    def change_interval(self):
        self.interval = (self.interval * 2) % 8
        if self.interval == 0:
            self.interval = 1
        self.tts.speak(f"Current interval: {self.interval} minute{'s' if self.interval > 1 else ''}")
        if self.selected_asset:
            self.retrieve_ohlc_data()
            self.create_chart()


async def main():
    tool = TechnicalAnalysisTool()
    await tool.run()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    loop.close()
