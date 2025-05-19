# config.py

import os
from dotenv import load_dotenv
from typing import List, Optional, Set # Added typing

load_dotenv()

class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass

class BaseConfig:
    # --- Core Secrets & Settings (Required) ---
    SECRET_KEY: Optional[str] = os.getenv("SECRET_KEY")
    DB_CONNECTION_STRING: Optional[str] = os.getenv("DB_CONNECTION_STRING")
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL", "redis://localhost:6379/0") # Added default

    # --- Environment ---
    ENV: str = os.getenv("ENV", "development").lower()
    ALLOWED_ENVS: Set[str] = {"development", "production", "testing"} # Added testing
    DEBUG: bool = False # Default to False, overridden by DevelopmentConfig

    # --- JWT ---
    JWT_EXPIRATION_DELTA: int = int(os.getenv("JWT_EXPIRATION_DELTA", "3600")) # 1 hour default

    # --- CORS ---
    # Comma-separated list of allowed origins
    TRUSTED_ORIGINS_STR: str = os.getenv("TRUSTED_ORIGINS", "")
    TRUSTED_ORIGINS: List[str] = [o.strip() for o in TRUSTED_ORIGINS_STR.split(",") if o.strip()]

    # --- Plugin Specific Credentials ---
    # Example: Alpaca (others would follow similar pattern)
    ALPACA_API_KEY: Optional[str] = os.getenv("ALPACA_API_KEY")
    ALPACA_API_SECRET: Optional[str] = os.getenv("ALPACA_API_SECRET")
    # Add other plugin keys here as needed, e.g., POLYGON_API_KEY

    # --- Market Service & Plugin Behavior ---
    DEFAULT_PLUGIN_CHUNK_SIZE: int = int(os.getenv("DEFAULT_PLUGIN_CHUNK_SIZE", "500"))
    MAX_PLUGIN_CHUNKS_PER_GAP: int = int(os.getenv("MAX_PLUGIN_CHUNKS_PER_GAP", "5"))
    DEFAULT_CHART_POINTS: int = int(os.getenv("DEFAULT_CHART_POINTS", "200")) # Used when 'since' is not provided

    # --- Caching TTLs (Time-To-Live in seconds) ---
    CACHE_TTL_1M_BAR_GROUP: int = int(os.getenv("CACHE_TTL_1M_BAR_GROUP", 60 * 60 * 24)) # 24 hours
    CACHE_TTL_OHLCV_RESULT: int = int(os.getenv("CACHE_TTL_OHLCV_RESULT", 300)) # 5 minutes
    # CACHE_TTL_LATEST_BAR_RESULT: Base TTL, MarketService makes it dynamic
    CACHE_TTL_LATEST_BAR_BASE: int = int(os.getenv("CACHE_TTL_LATEST_BAR_BASE", "10")) # Base 10s, MarketService adjusts

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FILE: Optional[str] = os.getenv("LOG_FILE") # Optional file path

    @classmethod
    def validate(cls):
        """Validates required configuration settings."""
        errors: List[str] = []

        # 1) ENV must be recognized
        if cls.ENV not in cls.ALLOWED_ENVS:
            errors.append(f"Invalid ENV '{cls.ENV}'. Must be one of {sorted(cls.ALLOWED_ENVS)}")

        # 2) Required secrets/connection strings
        for var_name in ("SECRET_KEY", "DB_CONNECTION_STRING", "REDIS_URL"):
            if not getattr(cls, var_name):
                errors.append(f"Missing required environment variable or default: {var_name}")

        # 3) Validate positive integers for certain settings
        for var_name, value in [
            ("JWT_EXPIRATION_DELTA", cls.JWT_EXPIRATION_DELTA),
            ("DEFAULT_PLUGIN_CHUNK_SIZE", cls.DEFAULT_PLUGIN_CHUNK_SIZE),
            ("MAX_PLUGIN_CHUNKS_PER_GAP", cls.MAX_PLUGIN_CHUNKS_PER_GAP),
            ("DEFAULT_CHART_POINTS", cls.DEFAULT_CHART_POINTS),
            ("CACHE_TTL_1M_BAR_GROUP", cls.CACHE_TTL_1M_BAR_GROUP),
            ("CACHE_TTL_OHLCV_RESULT", cls.CACHE_TTL_OHLCV_RESULT),
            ("CACHE_TTL_LATEST_BAR_BASE", cls.CACHE_TTL_LATEST_BAR_BASE),
        ]:
             if value <= 0:
                 errors.append(f"Configuration value for '{var_name}' must be positive, got '{value}'")

        # 4) Validate Log Level
        if cls.LOG_LEVEL not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
             errors.append(f"Invalid LOG_LEVEL '{cls.LOG_LEVEL}'. Must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL.")


        if errors:
            raise ConfigError("Configuration validation failed: " + "; ".join(errors))

class DevelopmentConfig(BaseConfig):
    DEBUG = True
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG").upper() # Default to DEBUG in dev

class ProductionConfig(BaseConfig):
    DEBUG = False
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper() # Default to INFO in prod

    @classmethod
    def validate(cls):
        """Validate production-specific settings."""
        super().validate() # Run base validation first
        errors: List[str] = []
        # Production must define trusted origins for CORS
        if not cls.TRUSTED_ORIGINS:
            errors.append("In production (ENV=production), TRUSTED_ORIGINS must be defined and non-empty")
        # Add other production checks here (e.g., ensure certain debug flags are off)
        if errors:
             raise ConfigError("Production configuration validation failed: " + "; ".join(errors))

class TestingConfig(BaseConfig):
    """Configuration for running tests."""
    ENV = "testing"
    DEBUG = True # Often helpful for tests
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "WARNING").upper() # Less verbose for tests usually
    # Use separate DB/Redis if needed for test isolation
    DB_CONNECTION_STRING: Optional[str] = os.getenv("TEST_DB_CONNECTION_STRING", BaseConfig.DB_CONNECTION_STRING)
    REDIS_URL: Optional[str] = os.getenv("TEST_REDIS_URL", BaseConfig.REDIS_URL)
    # Maybe shorter JWT expiry for tests
    JWT_EXPIRATION_DELTA: int = int(os.getenv("TEST_JWT_EXPIRATION_DELTA", "60")) # 1 minute

def get_config():
    """Factory function to get the appropriate config class based on ENV."""
    env = BaseConfig.ENV
    if env == "production":
        return ProductionConfig
    elif env == "testing":
        return TestingConfig
    else: # Default to development
        # Ensure ENV is explicitly 'development' if not production/testing
        if env != "development":
             # Log a warning if ENV is unrecognized but falling back to development
             # Note: Logging might not be configured yet when this runs.
             print(f"WARNING: Unrecognized ENV value '{env}'. Defaulting to DevelopmentConfig.")
        return DevelopmentConfig

# Get the config class based on environment
# Validation will happen later in create_app using config_class.validate()
config_class = get_config()
