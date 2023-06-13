import numpy as np
import simpleaudio as sa
from scipy import interpolate
import asyncio

class Sonification:
    def __init__(self):
        self.sample_rate = 44100  # Set the desired sample rate

    async def play_sine_wave_from_data(self, data):
        try:
            if isinstance(data, np.ndarray):
                data = data.flatten().tolist()
            elif not isinstance(data, list):
                data = [data]
            data = [float(item) for item in data]
        except ValueError:
            print("Unable to convert all data to floats.")
            return

        min_freq = 220  # Hz
        max_freq = 880  # Hz

        # Normalize data
        normalized_data = (data - np.min(data)) / (np.max(data) - np.min(data))

        # Interpolate data
        x = np.linspace(0, 1, len(normalized_data))
        f = interpolate.interp1d(x, normalized_data)
        xnew = np.linspace(0, 1, 10000)  # Interpolate to 10000 data points
        ynew = f(xnew)

        # Calculate frequency changes over time
        frequencies = ynew * (max_freq - min_freq) + min_freq
        t = np.linspace(0, 1, len(frequencies), False)
        phase = 2 * np.pi * np.cumsum(frequencies) / self.sample_rate
        audio = np.sin(phase)

        # Normalize to 16-bit range
        audio *= 32767 / np.max(np.abs(audio))
        audio = audio.astype(np.int16)

        # Start playback
        play_obj = sa.play_buffer(audio, 2, 2, self.sample_rate)

        # Wait for playback to finish before exiting
        while play_obj.is_playing():
            await asyncio.sleep(0.1)

    def _convert_to_float(self, item):
        if isinstance(item, np.ndarray):
            return item.tolist()
        elif isinstance(item, str):
            return float(item)
        else:
            return item
