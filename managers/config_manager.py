import json
import os

class ConfigManager:
    """A singleton class to manage application configurations."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._config = {}
            cls._instance.config_file = 'config.json'
            cls._instance.load_config()
        return cls._instance

    def load_config(self):
        """Load configuration settings from a JSON file."""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as file:
                try:
                    self._config = json.load(file)
                except json.JSONDecodeError:
                    print("Error: Configuration file is corrupted. Using default settings.")
                    self._config = self.default_config()
        else:
            print("No configuration file found. Using default settings.")
            self._config = self.default_config()

    def save_config(self):
        """Save configuration settings to a JSON file."""
        with open(self.config_file, 'w') as file:
            json.dump(self._config, file, indent=4)

    def get(self, key, default=None):
        """Get a configuration value."""
        keys = key.split('.')
        value = self._config
        for k in keys:
            value = value.get(k, default)
            if value is default:
                break
        return value

    def set(self, key, value):
        """Set a configuration value."""
        keys = key.split('.')
        cfg = self._config
        for k in keys[:-1]:
            cfg = cfg.setdefault(k, {})
        cfg[keys[-1]] = value
        self.save_config()

    def default_config(self):
        """Return default configuration settings."""
        return {
            "appearance": {
                "background_color": "black",
                "foreground_color": "white",
                "chart_color_scheme": "dark",
                "line_thickness": 2,
                "font_size": 12
            },
            "accessibility": {
                "speech_enabled": True,
                "speech_verbosity": "normal",
                "keyboard_navigation_speed": "normal"
            },
            "data": {
                "auto_refresh_interval": 60,  # In seconds
                "use_cache": True
            },
            "sound": {
                "sound_enabled": True,
                "volume_level": 0.5,
                "custom_sounds_dir": None
            }
        }

    def update_config(self, new_settings):
        """Update multiple configuration settings."""
        self._config.update(new_settings)
        self.save_config()

# Global instance of ConfigManager
config_manager = ConfigManager()
