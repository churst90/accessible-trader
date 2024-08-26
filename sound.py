from pyo import *
import os
import threading

class AudioPresenter:
    def __init__(self, audio_representation, custom_sounds_dir=None):
        self.audio_representation = audio_representation
        self.server = Server().boot()  # Initialize the pyo server
        self.server.start()
        self.custom_sounds_dir = custom_sounds_dir  # Directory to load custom sounds from
        self.sounds = []  # List to keep track of playing sounds
        self.playing = False  # Track whether audio is playing
        self.stop_signal = threading.Event()  # Signal to stop playback
        self.playback_speed = 1.0  # Default playback speed

    def generate_tone(self, frequency, duration=0.1, volume=0.5, pan=0.0):
        """Generates a tone at a specific frequency, duration, volume, and panning using pyo."""
        if self.stop_signal.is_set():
            return
        tone = Sine(freq=frequency, mul=volume)
        panned_tone = Pan(tone, pan=pan).out()  # Pan the sound left to right
        time.sleep(duration)  # Sleep for the duration of the tone
        panned_tone.stop()  # Stop the tone after the duration has passed

    def play_series(self, values, duration=0.1, min_freq=200, max_freq=1000):
        """Plays a series of tones corresponding to a list of values."""
        min_value = min(values)
        max_value = max(values)
        value_range = max_value - min_value if max_value != min_value else 1

        num_values = len(values)
        # Adjust duration based on the number of data points and playback speed
        duration = max(0.01, min(0.1, 5 / num_values)) / self.playback_speed

        for i, value in enumerate(values):
            if self.stop_signal.is_set():
                break
            # Map value to frequency
            frequency = min_freq + ((value - min_value) / value_range) * (max_freq - min_freq)
            pan = (i / (num_values - 1)) * 2 - 1  # Calculate pan position from left (-1) to right (1)
            self.generate_tone(frequency=frequency, duration=duration, pan=pan)

    def play_audio(self):
        """Starts playing all the sounds generated from the audio representation."""
        if not self.playing:
            self.playing = True
            self.stop_signal.clear()
            if 'Price' in self.audio_representation:
                values = self.audio_representation['Price']['values']
                threading.Thread(target=self.play_series, args=(values,)).start()

    def stop_audio(self):
        """Stops all sounds."""
        self.stop_signal.set()
        for sound in self.sounds:
            sound.stop()
        self.sounds = []
        self.playing = False

    def modify_sound(self, indicator_name, new_sound_file):
        """Modify the sound for a specific indicator."""
        for properties in self.audio_representation.values():
            if properties.get('indicator_name') == indicator_name:
                properties['custom_sound'] = new_sound_file

    def set_playback_speed(self, speed):
        """Adjusts the playback speed."""
        self.playback_speed = max(0.1, min(5.0, speed))  # Limit speed between 0.1x and 5.0x
