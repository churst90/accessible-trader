from pyo import *
import os
import asyncio
from config import config_manager

class AudioPresenter:
    def __init__(self, event_bus):
        # Initialize the pyo server and start it
        self.server = Server().boot()
        self.server.start()
        self.event_bus = event_bus

        # Load sound settings from ConfigManager
        self.sound_enabled = config_manager.get('sound', {}).get('sound_enabled', True)
        self.volume_level = config_manager.get('sound', {}).get('volume_level', 0.5)
        self.custom_sounds_dir = config_manager.get('sound', {}).get('custom_sounds_dir', None)

        # Dictionary to keep track of playing sounds and playback control
        self.sounds = {}

        # Event subscriptions
        self.subscribe_to_events()

    def subscribe_to_events(self):
        """Subscribe to necessary events from the event bus."""
        self.event_bus.subscribe("data_fetched", self.on_data_fetched)
        self.event_bus.subscribe("alert_triggered", self.on_alert_triggered)

    async def on_data_fetched(self, data):
        """Play a sound when new data is fetched."""
        await self.play_sound("data_fetched")

    async def on_alert_triggered(self, alert_type):
        """Play a sound when an alert is triggered."""
        await self.play_sound(alert_type)

    async def play_sound(self, sound_type):
        """Play a predefined sound based on the type of event."""
        if not self.sound_enabled:
            return

        if self.custom_sounds_dir and os.path.exists(self.custom_sounds_dir):
            sound_file = os.path.join(self.custom_sounds_dir, f"{sound_type}.wav")
            if os.path.exists(sound_file):
                await asyncio.to_thread(self._play_wav_sound, sound_file)
                return

        # Fallback to generating a tone if custom sound is not available
        await asyncio.to_thread(self.generate_tone, 440, 0.2)  # Example tone

    def _play_wav_sound(self, sound_file):
        """Helper method to play a WAV file sound."""
        sound = SfPlayer(sound_file, loop=False, mul=self.volume_level).out()
        self.sounds[sound_file] = sound

    def generate_tone(self, frequency, duration=0.1):
        """Generate a tone at a specific frequency and duration."""
        if not self.sound_enabled:
            return

        tone = Sine(freq=frequency, mul=self.volume_level).out()
        time.sleep(duration)  # Blocking sleep, wrapped with asyncio.to_thread in the caller method
        tone.stop()

    def stop_all_sounds(self):
        """Stop all playing sounds."""
        for sound in self.sounds.values():
            sound.stop()
        self.sounds.clear()

    def set_volume(self, volume):
        """Set the volume level for audio playback."""
        self.volume_level = volume
        config_manager.set('sound.volume_level', volume)

    def modify_sound(self, sound_type, new_sound_file):
        """Modify the sound for a specific event type."""
        if not self.custom_sounds_dir:
            return

        custom_path = os.path.join(self.custom_sounds_dir, f"{sound_type}.wav")
        if os.path.exists(new_sound_file):
            os.replace(new_sound_file, custom_path)

    def set_playback_speed(self, speed):
        """Set the playback speed for sounds."""
        for sound in self.sounds.values():
            sound.setSpeed(speed)
