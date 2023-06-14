import pandas as pd
import pygame
import asyncio
from datetime import datetime
from speechmanager import SpeechManager
from sonification import Sonification
from bitstamp import BitstampAPI

class TechnicalAnalysisTool:
    def __init__(self):
        self.current_row_index = 0
        self.is_moving_vertically = False
        self.candle_columns = ["High", "Open", "Close", "Low"]
        self.sonification = Sonification()
        self.assets = []
        self.selected_asset = None
        self.ohlc_data = None
        self.chart = []
        self.current_series_index = 0
        self.current_column_index = 1
        self.current_row_index = 1
        self.current_row = 1
        self.current_column = 999
        self.step = 60  # in seconds
        self.timeframe_multiplier = 1
        self.interval = 1
        self.tts = SpeechManager()
        self.timeframes = ['Minute', 'Hour', 'Day', 'Week', 'Month', 'Year', 'YTD', 'All time']
        self.current_timeframe = 'Minute'
        self.bitstamp_api = BitstampAPI()

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
                    elif event.key == pygame.K_SPACE:
                        if self.current_series_index == 2:  # When focus is on the price series
                            await self.sonification.play_sine_wave_from_data(self.chart[self.current_series_index])

            window.fill((0, 0, 0))
            pygame.display.update()
            clock.tick(60)

        pygame.quit()

    def retrieve_asset_pairs(self):
        self.assets = self.bitstamp_api.retrieve_asset_pairs()

    async def select_asset_pair(self):
        selected_asset = await self.show_menu(self.assets, "Select Asset Pair")
        if selected_asset:
            self.selected_asset = selected_asset.replace("/", "").lower()
            self.tts.speak(f"Selected {self.selected_asset}")
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
        self.ohlc_data = self.bitstamp_api.retrieve_ohlc_data(self.selected_asset, self.step, 1000)
        if self.ohlc_data is not None:
            self.tts.speak(f"Loaded {self.interval} {self.current_timeframe} candle data for {self.selected_asset}")
        else:
            self.tts.speak("No data available for that time interval.")

    def create_chart(self):
        if self.ohlc_data is not None:
            # Create volume dataframe
            volume_df = pd.DataFrame({
                "Timestamp": self.ohlc_data["timestamp"],
                "Volume": self.ohlc_data["volume"]
            })

            # Create candles dataframe
            candles_df = pd.DataFrame({
                "Timestamp": self.ohlc_data["timestamp"],
                "Open": self.ohlc_data["open"],
                "High": self.ohlc_data["high"],
                "Low": self.ohlc_data["low"],
                "Close": self.ohlc_data["close"]
            })

            # Create price dataframe
            price_df = pd.DataFrame({
                "Timestamp": self.ohlc_data["timestamp"],
                "Price": self.ohlc_data["close"]
            })

            # Assign the created dataframes to the chart
            self.chart = [volume_df, candles_df, price_df]

            self.current_column_index = len(self.chart[self.current_series_index]) - 1
            self.current_column = self.chart[self.current_series_index]["Timestamp"][self.current_column_index]

            # Update the row index and row based on the number of columns in the current series
            self.current_row_index = len(self.chart[self.current_series_index].columns) - 1

            # Get the current row based on the row index
            if 0 <= self.current_row_index < len(self.chart[self.current_series_index].columns):  # Check if row index is valid
                self.current_row = self.chart[self.current_series_index].columns[self.current_row_index]
            else:
                self.current_row_index = 0
                self.current_row = 0

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
            timestamp = pd.to_datetime(self.current_column)

            if pd.isnull(timestamp):
                timestamp_str = 'NaT'
            else:
                timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')  # Convert to readable format

            if self.current_row_index < len(self.chart[self.current_series_index].columns):
                value = self.chart[self.current_series_index].loc[self.current_column_index, self.current_row]
                values_str = f"{self.current_row}: {value}"
            else:
                values_str = "Out of range"

            return f"{series_name}, {values_str}, Timestamp: {timestamp_str}" if self.is_moving_vertically else f"{series_name}, {values_str}"
        else:
            return "No data loaded"

    def change_series(self, direction):
        if self.chart:
            self.current_series_index = (self.current_series_index + direction) % len(self.chart)

            # Reset column indices when switching series
            self.current_column_index = len(self.chart[self.current_series_index]) - 1
            self.current_column = self.chart[self.current_series_index]["Timestamp"].iloc[self.current_column_index]

            # Set the row index to the last row (most recent row)
            self.current_row_index = len(self.chart[self.current_series_index].columns) - 1

            # Set the current row to the first cell in the row
            self.current_row = self.chart[self.current_series_index].columns[0]

            self.tts.speak(self.get_series_name(self.current_series_index))

    def move_along_data(self, direction):
        if self.chart:
            self.is_moving_vertically = True
            proposed_column_index = self.current_column_index + direction

            # Check if the proposed_column_index is within the valid range
            if 0 <= proposed_column_index < len(self.chart[self.current_series_index]):
                self.current_column_index = proposed_column_index
                self.current_column = self.chart[self.current_series_index]["Timestamp"].iloc[self.current_column_index]
                self.tts.speak(self.get_current_data())
            elif proposed_column_index < 0:
                self.tts.speak("You have reached the beginning of the data.")

    def move_between_rows(self, direction):
        if self.chart:
            self.is_moving_vertically = False
            proposed_row_index = self.current_row_index + direction

            # Check if the proposed_row_index is within the valid range
            if 0 <= proposed_row_index < len(self.chart[self.current_series_index].columns):
                self.current_row_index = proposed_row_index
                self.current_row = self.chart[self.current_series_index].columns[self.current_row_index]
                self.tts.speak(self.get_current_data())

    def change_timeframe(self):
        timeframe_steps = {
            'Minute': 60,  # 60 seconds
            'Hour': 60*60,  # 3600 seconds
            'Day': 60*60*24,  # 86400 seconds
            'Week': 60*60*24*7,  # 604800 seconds
            'Month': 60*60*24*30,  # 2592000 seconds (approximate)
            'Year': 60*60*24*365,  # 31536000 seconds (approximate)
            'YTD': 60*60*24*365,  # 31536000 seconds (approximate, considering it as a year)
            'All time': 60*60*24*365  # 31536000 seconds (approximate, considering it as a year)
        }

        # Get the index of current timeframe
        current_timeframe_index = self.timeframes.index(self.current_timeframe)
        # Move to the next timeframe
        new_timeframe_index = (current_timeframe_index + 1) % len(self.timeframes)
        self.current_timeframe = self.timeframes[new_timeframe_index]

        # Update the step according to the new timeframe
        self.step = timeframe_steps[self.current_timeframe]
        self.step = self.step * self.interval

        self.tts.speak(f"{self.interval} {self.current_timeframe}")

    def change_interval(self, direction):
        self.interval = max(1, self.interval + direction)
        self.step *= self.interval
        self.tts.speak(f"Interval changed to {self.interval}")

if __name__ == "__main__":
    tool = TechnicalAnalysisTool()
    asyncio.run(tool.run())
