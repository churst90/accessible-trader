import pandas as pd
import numpy as np
from collections import OrderedDict
from operator import itemgetter

class MarketProfile:
    def __init__(self, ohlc: pd.DataFrame, show_blocks=True):
        self.ohlc = ohlc
        self.period = 13
        self.row_size = 500
        self.show_blocks = show_blocks

    def set_price_thresholds(self, thresh):
        self.price_thresholds = thresh

    def set_period(self, period):
        """
        Set the window size for calculating TPO.
        """
        self.period = period

    def set_row_size(self, row_size):
        """
        Set the row size for calculating TPO.
        """
        self.row_size = row_size

    def split_into_periods(self):
        """
        Split the OHLC data into time periods defined by the user.
        """
        timeperiods = []
        start_index = 0
        end_index = self.period

        while end_index <= len(self.ohlc):
            timeperiods.append(self.ohlc.iloc[start_index:end_index])
            start_index = end_index
            end_index += self.period

        return timeperiods

    def calculate_tpo(self, period):
        # Calculate the high and low for this period
        high = period['high'].max()
        low = period['low'].min()
        price_bins = np.arange(low, high, self.row_size)

        tpo_dict = {}
        for price_bin in price_bins:
            tpo_count = ((period['low'] <= price_bin) & (period['high'] >= price_bin)).sum()
            tpo_dict[price_bin] = tpo_count
        return tpo_dict

    def tpo(self):
        """
        Calculate TPO for the given OHLC data.
        """
        timeperiods = self.split_into_periods()
        tpo_data = []
        for period in timeperiods:
            tpo_dict = self.calculate_tpo(period)
            tpo_data.append(tpo_dict)

        min_price = min(min(d.keys()) for d in tpo_data)
        max_price = max(max(d.keys()) for d in tpo_data)
        all_prices = np.arange(min_price, max_price+self.row_size, self.row_size)

        tpo_df = pd.DataFrame(index=all_prices)
        for i, d in enumerate(tpo_data):
            temp_series = pd.Series(d, name=timeperiods[i].index[0])
            tpo_df = pd.concat([tpo_df, temp_series], axis=1)

        tpo_df.fillna("", inplace=True)
        tpo_df.sort_index(ascending=False, inplace=True)  # Sort index in descending order (reverse rows)

        return tpo_df
