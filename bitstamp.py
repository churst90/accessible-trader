import requests
import pandas as pd

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

    def retrieve_ohlc_data(self, selected_asset, step, limit):
        url = f"https://www.bitstamp.net/api/v2/ohlc/{selected_asset}/?step={step}&limit={limit}"
        response = requests.get(url)
        if response.status_code == 200:
            ohlc_data = response.json()
            if "data" in ohlc_data and "ohlc" in ohlc_data["data"]:
                data = ohlc_data["data"]["ohlc"]
                columns = ["timestamp", "high", "open", "close", "low", "volume"]
                return pd.DataFrame(data, columns=columns)
        return None
