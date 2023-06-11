import numpy as np

class Indicators:
  def __init__(self):
    pass

  def vpvr(self, prices, volumes, period):
    # Initialize the Value area high and low arrays
    value_area_high = np.zeros(prices.shape[0])
    value_area_low = np.zeros(prices.shape[0])
    poc_values = np.zeros(prices.shape[0])
    for i in range(prices.shape[0]- period):
      # Calculate the current Value area high and low
      high_range = np.max(prices[i:i+period])
      low_range = np.min(prices[i:i+period])
      value_area_high[i] = np.sum(volumes[i:i+period][(prices[i:i+period] >= high_range)]) / np.sum(volumes[i:i+period])
      value_area_low[i] = np.sum(volumes[i:i+period][(prices[i:i+period] <= low_range)]) / np.sum(volumes[i:i+period])
      # Get the current POC value
      poc_values[i] = prices[np.argmax(volumes[i:i+period])]
    return value_area_high, value_area_low, poc_values

  def tpo(self, high_prices, low_prices, volumes, period, tick_length):
    # Initialize the high_range_list and low_range_list
    high_range_list = []
    low_range_list = []
    total_trades_list = []
    poc_sum = 0
    poc_vol = 0
    for i in range(0, high_prices.shape[0] - period):
      # Get the current high range
      high_range = np.min(high_prices[i:i+period])
      high_range_list.append(high_range)
      # Get the current low range
      low_range = np.min(low_prices[i:i+period])
      low_range_list.append(low_range)
      # Get the volume within the high and low range
      volume_within_range = volumes[i:i+period][(high_prices[i:i+period] >= low_range) & (low_prices[i:i+period] <= high_range)]
      total_volume = volume_within_range.sum()
      # Calculate the estimated number of trades
      estimated_trades = total_volume / tick_length
      total_trades_list.append(estimated_trades)
      #calculate the point of control
      tpo_vol = volume_within_range.sum()
      poc_sum += (high_range + low_range) * tpo_vol
      poc_vol += tpo_vol
    poc = poc_sum / poc_vol
    # Print the TPO chart with the number of ticks
    for i in range(len(high_range_list)):
      print(f"High: {high_range_list[i]}, ticks: {int(total_trades_list[i])}, Low: {low_range_list[i]}")
    return high_range_list, low_range_list, total_trades_list, poc

  def divergence(self, prices, rsi, period):
    # Initialize the divergence message
    divergence_message = ""
    for i in range(prices.shape[0]- period):
      # Check for bullish divergence
      if rsi[i] < 30 and prices[i] > prices[i+period]:
        divergence_message += f"Bullish divergence found at index {i}\n"

      # Check for bearish divergence
      elif rsi[i] > 70 and prices[i] < prices[i+period]:
        divergence_message += f"Bearish divergence found at index {i}\n"

    # Return the divergence message
    return divergence_message
