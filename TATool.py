import pandas as pd
import pygame
import asyncio
from datetime import datetime
from speechmanager import SpeechManager
from sonification import Sonification
from volumeprofile import VolumeProfile
from marketprofile import MarketProfile
from api\apimanager import ApiManager
from candles import Candles

class TechnicalAnalysisTool:
    def __init__(self):
        self.api = ApiManager()
        self.current_row_index = 0
        self.is_moving_vertically = False
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
        pygame.display.set_caption("Accessible Trader")

        clock = pygame.time.Clock()

#        self.retrieve_asset_pairs()
#        await self.select_asset_pair()

        if self.selected_asset is not None:
            self.retrieve_ohlc_data()
            self.create_chart()

    def chart_navigation(self):
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
                        self.select_api()
                    elif event.key == pygame.K_F2:
                        self.select_api_category()
                        # If the shift key is also being pressed
                        if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                            self.change_interval(-1)
                        else:
                            self.change_interval(1)
                    elif event.key == pygame.K_F3:
                        self.get_asset_pair()
                    elif event.key == pygame.K_F6:
                        self.get_api_data()
                        self.create_chart()
                    elif event.key == pygame.K_SPACE:
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
            # Create market profile series
            tpo = MarketProfile(self.ohlc_data)
#            tpo.set_period(150)
#            tpo.set_row_size(15)
            tpo.set_price_thresholds((30, 70))
            tpo_df = tpo.tpo()

            # Create volume series
            volume = VolumeProfile(self.ohlc_data)
#            volume.set_window_size(60)
#            volume.set_row_size(30)
#            volume.set_volume_thresholds((30, 70))
            volume_df = volume.calculate_vpfr()

            # Create candles dataframe
            candles_df = Candles(self.ohlc_data).ha_candles

            # Create price dataframe
#            price_df = pd.DataFrame(self.ohlc_data.loc["close"]).T
#            price_df.index = ['Price']

            # Assign the created dataframes to the chart
            self.chart = [candles_df, volume_df, tpo_df]

            self.current_series_index = 0
            self.current_column_index = len(self.chart[self.current_series_index].columns) - 1
            self.current_row_index = 0
            self.current_row = self.chart[self.current_series_index].columns[0]
            self.current_column = self.chart[self.current_series_index].columns[self.current_column_index]

            self.tts.speak(self.get_series_name(self.current_series_index))
            self.tts.speak(self.get_current_data())

    def get_series_name(self, series_index):
        series_names = ["Candles", "Volume Profile", "Market Profile"]
        if 0 <= series_index < len(series_names):
            return series_names[series_index]
        else:
            return ""

    def get_current_data(self, include_row=False, include_column=False):
        if self.chart:
            series_name = self.get_series_name(self.current_series_index)
            current_dataframe = self.chart[self.current_series_index]

            if self.current_row_index < len(current_dataframe.index) and self.current_column_index < len(current_dataframe.columns):
                row_header = str(current_dataframe.index[self.current_row_index])
                column_header = str(current_dataframe.columns[self.current_column_index])
                value = current_dataframe.iat[self.current_row_index, self.current_column_index]

                output = ""

                if include_row:
                    output += f"{row_header}. "
                if include_column:
                    output += f"{column_header}: "
                output += str(value)

                return output

        return "Out of range" if self.chart else "No data loaded"

    def change_series(self, direction):
        if self.chart:
            self.current_series_index = (self.current_series_index + direction) % len(self.chart)

            # Preserve the current column index before changing series
            prev_column_index = self.current_column_index

            # Check if previous column index is within the range of new series columns
            if prev_column_index < len(self.chart[self.current_series_index].columns):
                # If it is, keep current column index as the previous one
                self.current_column_index = prev_column_index
            else:
                # If it's not, set column index to the last index of the new series
                self.current_column_index = len(self.chart[self.current_series_index].columns) - 1

            self.current_column = self.chart[self.current_series_index].columns[self.current_column_index]
            self.current_row_index = 0
            self.current_row = self.chart[self.current_series_index].index[0]

            self.tts.speak(self.get_series_name(self.current_series_index))

    def move_along_data(self, direction):
        if self.chart:
            proposed_column_index = self.current_column_index + direction
    
            # Check if the proposed_column_index is within the valid range
            if 0 <= proposed_column_index < len(self.chart[self.current_series_index].columns):
                self.current_column_index = proposed_column_index
                self.current_column = self.chart[self.current_series_index].columns[self.current_column_index]
                self.tts.speak(self.get_current_data(include_column=True))

    def move_between_rows(self, direction):
        if self.chart:
            proposed_row_index = self.current_row_index + direction

            # Check if the proposed_row_index is within the valid range
            if 0 <= proposed_row_index < len(self.chart[self.current_series_index].index):
                self.current_row_index = proposed_row_index
                self.current_row = self.chart[self.current_series_index].index[self.current_row_index]
                self.tts.speak(self.get_current_data(include_row=True))

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
