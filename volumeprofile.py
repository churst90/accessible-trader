import pandas as pd
import numpy as np

class VolumeProfile:
    def __init__(self, data):
        self.data = data
        self.window_size = 60
        self.row_size = 30
        self.volume_thresholds = (30, 70)

    def calculate_volume_profile(self, df, visible_range=False):
        epsilon = np.random.uniform(low=-0.00001, high=0.00001, size=(df['close'].shape))
        price_bins = pd.cut(df['close'] + epsilon, bins=self.row_size)
        df['price_bin'], self.bin_intervals = pd.factorize(price_bins)
        if visible_range:
            df['price_bin'] = df['price_bin'] % self.row_size
        volume_at_price = df.groupby(['time_bin', 'price_bin'])['volume'].sum()
        return volume_at_price

    def calculate_nodes(self, volume_at_price):
        low_threshold, high_threshold = np.percentile(volume_at_price, self.volume_thresholds)

        lvn = {k: (v, self.bin_intervals[k[1]]) for k, v in zip(volume_at_price[volume_at_price <= low_threshold].index, volume_at_price[volume_at_price <= low_threshold].values)} if not volume_at_price[volume_at_price <= low_threshold].empty else {}
        hvn = {k: (v, self.bin_intervals[k[1]]) for k, v in zip(volume_at_price[volume_at_price >= high_threshold].index, volume_at_price[volume_at_price >= high_threshold].values)} if not volume_at_price[volume_at_price >= high_threshold].empty else {}
    
        # Adjust lvn values for overlap with hvn
        for k, v in lvn.items():
            if k in hvn:
                lvn[k] = (max(0, v[0] - hvn[k][0]), v[1])  # Take the difference in volume and keep the price range

        poc = {volume_at_price.idxmax(): (self.bin_intervals[volume_at_price.idxmax()[1]].mid, volume_at_price.max())} if not volume_at_price.empty else {}  # Return price, not max volume

        return {'hvn': hvn, 'lvn': lvn, 'poc': poc}

    def build_df(self, volume_profile):
        volume_list = []
        for time_bin, group in volume_profile.groupby(level=0):
            nodes = self.calculate_nodes(group)
            for price_level, volume in group.items():
                price_range = self.bin_intervals[price_level[1]]
                node_list = []
                for node in nodes:
                    if price_level in nodes[node]:
                        node_list.append((node, nodes[node][price_level]))
                # Add 'No Node' if node_list is empty
                if not node_list:
                    node_list.append(('No Node', (0, price_range)))
                row = {'time_bin': time_bin, 
                       'price_level': f"price: {price_range.left}, {price_range.right}", 
                       'volume': volume, 
                       'node_index': node_list}
                volume_list.append(row)

        volume_df = pd.DataFrame(volume_list)
        volume_df = volume_df.set_index(['time_bin', 'price_level'])

        # Fill NaNs in the 'volume' column with 0
        volume_df['volume'] = volume_df['volume'].fillna(0)

        # Pivot the DataFrame
        volume_df = volume_df.pivot_table(index='price_level', columns='time_bin', values='volume', aggfunc='first', fill_value=0)

        # Sort the DataFrame based on 'time_bin'
        volume_df.sort_index(axis=1, ascending=True, inplace=True)

        # Reverse the order of rows
        volume_df = volume_df.iloc[::-1]

        return volume_df

    def calculate_vpfr(self):
        df = self.data.copy()
        df['time_bin'] = (df.index // self.window_size * self.window_size).astype(int)
        volume_profile = self.calculate_volume_profile(df)
        return self.build_df(volume_profile)

    def calculate_vpvr(self):
        df = self.data.copy()
        df['time_bin'] = (df.index // (self.window_size * self.row_size) * self.window_size * self.row_size).astype(int)
        volume_profile = self.calculate_volume_profile(df, visible_range=True)
        return self.build_df(volume_profile)

    def set_row_size(self, size):
        self.row_size = size

    def set_window_size(self, size):
        self.window_size = size

    def set_volume_thresholds(self, thresh):
        self.volume_thresholds = thresh
