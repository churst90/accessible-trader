import requests
import pandas as pd
from datetime import datetime

class BitstampAPI:
    def __init__(self):
        pass

    def retrieve_asset_pairs(self):
        response = requests.get("https://www.bitstamp.net/api/v2/trading-pairs-info/")
        if response.status_code == 200:
            asset_pairs = response.json()
            return [pair["name"] for pair in asset_pairs]
        else:
            return []

    def retrieve_ohlc_data(self, asset, step, limit):
        url = f"https://www.bitstamp.net/api/v2/ohlc/{asset}/"
        params = {
            "step": step,
            "limit": limit
        }
        response = requests.get(url, params=params)

        if response.status_code == 200:
            data = response.json()
            if "data" in data and "ohlc" in data["data"]:
                ohlc_data = data["data"]["ohlc"]
#                print(ohlc_data)
                ohlc_df = pd.DataFrame(ohlc_data)
                print(ohlc_df)

                # Convert to numeric values
                ohlc_df["timestamp"] = pd.to_numeric(ohlc_df["timestamp"]).astype(int)
                ohlc_df[["open", "high", "low", "close", "volume"]] = ohlc_df[["open", "high", "low", "close", "volume"]].astype(float)
            
                # Convert "Timestamp" column to datetime
                ohlc_df["timestamp"] = pd.to_datetime(ohlc_df["timestamp"], unit='s')  # The unit parameter is set to 's' to denote that the original input is in seconds.
                return ohlc_df

        return None
