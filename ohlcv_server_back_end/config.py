# config.py

import os
from dotenv import load_dotenv

load_dotenv()

class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass

class BaseConfig:
    # Required
    SECRET_KEY            = os.getenv("SECRET_KEY")
    DB_CONNECTION_STRING  = os.getenv("DB_CONNECTION_STRING")
    REDIS_URL             = os.getenv("REDIS_URL")

    # Alpaca credentials (for stocks plugin)
    ALPACA_API_KEY        = os.getenv("ALPACA_API_KEY")
    ALPACA_API_SECRET     = os.getenv("ALPACA_API_SECRET")

    # Optional with defaults
    JWT_EXPIRATION_DELTA  = int(os.getenv("JWT_EXPIRATION_DELTA", "3600"))
    TRUSTED_ORIGINS       = [o for o in os.getenv("TRUSTED_ORIGINS", "").split(",") if o]

    # Environment marker
    ENV                   = os.getenv("ENV", "development").lower()
    ALLOWED_ENVS          = {"development", "production"}

    DEBUG                 = False

    @classmethod
    def validate(cls):
        errors = []
        # 1) ENV must be recognized
        if cls.ENV not in cls.ALLOWED_ENVS:
            errors.append(f"Invalid ENV '{cls.ENV}'. Must be one of {sorted(cls.ALLOWED_ENVS)}")
        # 2) Required secrets
        for var in ("SECRET_KEY", "DB_CONNECTION_STRING", "REDIS_URL"):
            if not getattr(cls, var):
                errors.append(f"Missing required environment variable: {var}")
        if errors:
            raise ConfigError("; ".join(errors))

class DevelopmentConfig(BaseConfig):
    DEBUG = True

class ProductionConfig(BaseConfig):
    DEBUG = False

    @classmethod
    def validate(cls):
        super().validate()
        if not cls.TRUSTED_ORIGINS:
            raise ConfigError("In production, TRUSTED_ORIGINS must be defined and non-empty")

def get_config():
    env = BaseConfig.ENV
    if env == "production":
        return ProductionConfig
    else:
        return DevelopmentConfig

# No import-time validation — we’ll do that in create_app()
config_class = get_config()
