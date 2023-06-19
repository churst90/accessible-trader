import pandas as pd
import numpy as np

class Candles:
    def __init__(self, ohlc_data):
        self.ohlc_data = ohlc_data.copy()

        if 'volume' in self.ohlc_data.columns:
            self.ohlc_data.drop('volume', axis=1, inplace=True)

        self.standard_candles = self.create_candles(self.ohlc_data)
        self.ha_candles = self.create_heikin_ashi_candles()
        self.active_candles = self.standard_candles

    def create_dataframe(self, df, prefix=''):
        new_df = df.copy()
        new_df[f'{prefix}close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        new_df[f'{prefix}open'] = (df['open'].shift(1) + df['close'].shift(1)) / 2
        new_df.iloc[0, new_df.columns.get_loc(f'{prefix}open')] = df.iloc[0, df.columns.get_loc('open')]
        new_df[f'{prefix}high'] = new_df[[f'{prefix}open', f'{prefix}close', 'high']].max(axis=1)
        new_df[f'{prefix}low'] = new_df[[f'{prefix}open', f'{prefix}close', 'low']].min(axis=1)
        return new_df

    def create_candles(self, df):
        candles = self.create_dataframe(df)
        candles['Prev Open'] = candles['open'].shift(1)
        candles['Prev Close'] = candles['close'].shift(1)
        candles['Type'] = candles.apply(self.detect_single_candlestick_pattern, axis=1)
        candles['Upper Wick'] = self.upper_wick(candles)
        candles['Body'] = self.body(candles)
        candles['Lower Wick'] = self.lower_wick(candles)
        return candles

    def create_heikin_ashi_candles(self):
        ha_data = pd.DataFrame()
        ha_data['HA_close'] = (self.ohlc_data['open'] + self.ohlc_data['high'] + self.ohlc_data['low'] + self.ohlc_data['close']) / 4
        ha_data['HA_open'] = (self.ohlc_data['open'].shift(1) + self.ohlc_data['close'].shift(1)) / 2
        ha_data.iloc[0, ha_data.columns.get_loc('HA_open')] = self.ohlc_data.iloc[0, self.ohlc_data.columns.get_loc('open')]
        ha_data['HA_high'] = ha_data[['HA_open', 'HA_close']].join(self.ohlc_data['high']).max(axis=1)
        ha_data['HA_low'] = ha_data[['HA_open', 'HA_close']].join(self.ohlc_data['low']).min(axis=1)
        
        ha_candles = self.create_candles(ha_data.rename(columns={'HA_open': 'open', 'HA_close': 'close', 'HA_high': 'high', 'HA_low': 'low'}))
        return ha_candles.T

    def upper_wick(self, df):
        return df.apply(lambda row: (row['high'] - max(row['open'], row['close'])) / row['high'] * 100, axis=1)

    def body(self, df):
        return df.apply(lambda row: abs(row['open'] - row['close']) / row['open'] * 100, axis=1)

    def lower_wick(self, df):
        return df.apply(lambda row: (min(row['open'], row['close']) - row['low']) / min(row['open'], row['close']) * 100, axis=1)

    def detect_single_candlestick_pattern(self, row):
        op, hi, lo, cl = row['open'], row['high'], row['low'], row['close']
        prev_op, prev_cl = row.get('Prev Open', np.nan), row.get('Prev Close', np.nan)
        candle_range = hi - lo
        upper_wick = hi - max(op, cl)
        lower_wick = min(op, cl) - lo
        body = abs(op - cl)

        if np.isnan(prev_op) or np.isnan(prev_cl):
            return 'No Pattern'

        if candle_range == 0:
            return 'No Pattern'

        if body / candle_range < 0.1:
            if upper_wick / candle_range > 0.1 and lower_wick / candle_range > 0.1:
                return 'Doji'
            if upper_wick / candle_range > 0.1 and lower_wick / candle_range < 0.1:
                return 'Topping Tail'
            if upper_wick / candle_range < 0.1 and lower_wick / candle_range > 0.1:
                return 'Bottoming Tail'

        if body / candle_range > 0.6:
            if op > cl:  # Bearish
                if prev_cl > prev_op and cl < prev_op:
                    return 'Bearish Engulfing'
            else:  # Bullish
                if prev_cl < prev_op and cl > prev_op:
                    return 'Bullish Engulfing'

        if upper_wick / candle_range < 0.1:
            if op > cl:  # Bearish
                if lower_wick / body > 2:
                    return 'Hammer'
            else:  # Bullish
                if body != 0 and lower_wick / body > 2:
                    return 'Hanging Man'

        if lower_wick / candle_range < 0.1:
            if op > cl:  # Bearish
                if body != 0 and upper_wick / body > 2:
                    return 'Shooting Star'
            else:  # Bullish
                if body != 0 and upper_wick / body > 2:
                    return 'Inverted Hammer'
                if upper_wick == 0 and lower_wick == 0:
                    if cl > op:
                        return 'Bullish Marubozu'
                    elif cl < op:
                        return 'Bearish Marubozu'
                if body / candle_range < 0.3:
                    return 'Spinning Top'

        return 'No Pattern'
    
    def set_active_candles(self, candle_type):
        if candle_type == 'standard':
            self.active_candles = self.standard_candles
        elif candle_type == 'heikin_ashi':
            self.active_candles = self.ha_candles
        else:
            raise ValueError("candle_type must be either 'standard' or 'heikin_ashi'")
