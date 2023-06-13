import numpy as np

class Indicators:
  def __init__(self):
    pass

  def vpvr(self, prices, volumes, window_size, num_rows):
    # Initialize the VPVR array
    vpvr_array = np.zeros((prices.shape[0] - window_size, num_rows))

    for i in range(window_size, prices.shape[0]):
      # Get the data in the current window
      prices_window = prices[i-window_size:i]
      volumes_window = volumes[i-window_size:i]

      # Determine price levels in the current window
      min_price, max_price = np.min(prices_window), np.max(prices_window)
      price_levels = np.linspace(min_price, max_price, num_rows)

      # Initialize volume at each level to 0
      volume_at_levels = np.zeros(num_rows)

      # Assign each price to a level and add its volume
      for price, volume in zip(prices_window, volumes_window):
        level = int((price - min_price) / (max_price - min_price) * num_rows)
        volume_at_levels[level] += volume

      # Normalize volume at each level and add to the VPVR array
      vpvr_array[i-window_size] = volume_at_levels / np.sum(volume_at_levels)

    return vpvr_array

  def tpo(self, prices, window_size, num_rows):
    tpo_array = np.zeros((prices.shape[0] - window_size, num_rows))

    for i in range(prices.shape[0] - window_size):
      window_prices = prices[i:i+window_size]
      min_price, max_price = np.min(window_prices), np.max(window_prices)
      price_bins = np.linspace(min_price, max_price, num_rows)

      for j, price in enumerate(window_prices):
        price_level = np.digitize(price, price_bins) - 1
        tpo_array[i][price_level] += 1

    # Normalize the TPO counts to form a distribution
    tpo_array = tpo_array / np.sum(tpo_array, axis=1, keepdims=True)

    return tpo_array

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
