import os
from dotenv import load_dotenv

load_dotenv()

class ConfigError(Exception):
    """Custom exception for configuration errors."""
    pass

class Config:
    """
    Base configuration class with environment variable validation.
    """
    SECRET_KEY = os.getenv("SECRET_KEY", None)
    DB_CONNECTION_STRING = os.getenv("DB_CONNECTION_STRING", None)
    JWT_EXPIRATION_DELTA = int(os.getenv("JWT_EXPIRATION_DELTA", 3600))
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost")
    TRUSTED_ORIGINS = os.getenv("TRUSTED_ORIGINS", "").split(",")
    ENV = os.getenv("ENV", "development").lower()

    @staticmethod
    def validate():
        """
        Validate critical environment variables.
        """
        required_vars = {
            "SECRET_KEY": Config.SECRET_KEY,
            "DB_CONNECTION_STRING": Config.DB_CONNECTION_STRING,
            "REDIS_URL": Config.REDIS_URL,
        }
        missing_vars = [key for key, value in required_vars.items() if not value]
        if missing_vars:
            raise ConfigError(f"Missing required environment variables: {', '.join(missing_vars)}")

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False

    @staticmethod
    def validate():
        """
        Additional validation for production environments.
        """
        super(ProductionConfig, ProductionConfig).validate()
        if Config.TRUSTED_ORIGINS == [""]:
            raise ConfigError("TRUSTED_ORIGINS must be defined in production.")

def get_config():
    ENV = Config.ENV
    if ENV == "production":
        ProductionConfig.validate()
        return ProductionConfig
    else:
        DevelopmentConfig.validate()
        return DevelopmentConfig

# Perform validation
try:
    config_class = get_config()
except ConfigError as e:
    import logging
    logging.critical(f"Configuration validation failed: {e}")
    raise
