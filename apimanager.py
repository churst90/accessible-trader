from api\bitstamp import BitstampApi

class ApiManager:

    def __init__(self):
        self.api_name = None
        self.api_key = None
        self.api_list = ["BitstampApi", "CoinMarketCapApi", "FinancialModelingPrepApi"]
        self.limit = None
        self.step = None

    def get_api_list(self):
        return self.api_list

    def get_asset_pairs(self):
        pairs = self.api_name.retrieve_asset_pairs()
        return pairs

    def get_api_data(self):
        data = self.api_name.retrieve_ohlc_data()
        return data

    def set_api_name(self, api):
        self.api_name = api()

    def set_limit(self, limit):
        self.limit = limit

    def set_step(self, step):
        self.step = step