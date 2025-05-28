# models/user_config_models.py

from sqlalchemy import Column, Integer, String, Text, Boolean, TIMESTAMP, ForeignKey, DECIMAL, JSON, UniqueConstraint
from sqlalchemy.sql import func # For CURRENT_TIMESTAMP, now()
from sqlalchemy.orm import relationship

# Import the UserConfigsBase from your setup file
from app_extensions.user_configs_db_setup import UserConfigsBase

class UserApiCredential(UserConfigsBase):
    __tablename__ = 'user_api_credentials'

    credential_id = Column(Integer, primary_key=True, autoincrement=True, comment='Primary key for the credential')
    user_id = Column(Integer, nullable=False, index=True, comment='Foreign key referencing the main users table ID (in userdb)')
    service_name = Column(String(100), nullable=False, comment='Identifier for the service/plugin (e.g., alpaca, oanda, binance)')
    credential_name = Column(String(255), nullable=False, comment='User-defined alias/name for this API key set')
    encrypted_api_key = Column(Text, nullable=False, comment='Encrypted API key')
    encrypted_api_secret = Column(Text, nullable=True, comment='Encrypted API secret (optional)')
    encrypted_aux_data = Column(Text, nullable=True, comment='Encrypted auxiliary data (e.g., passphrase, subaccount ID) as JSON string')
    is_testnet = Column(Boolean, nullable=False, default=False, comment='True if these credentials are for a testnet/sandbox environment')
    notes = Column(Text, nullable=True, comment='User-provided notes about these credentials')
    created_at = Column(TIMESTAMP, server_default=func.now(), comment='Timestamp of creation')
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), comment='Timestamp of last update')

    # Define a unique constraint for user_id, service_name, and credential_name
    # This ensures a user can't have multiple credentials with the exact same name for the same service.
    __table_args__ = (UniqueConstraint('user_id', 'service_name', 'credential_name', name='uk_user_service_credential_name'),)

    # Relationship to UserTradingBot (one credential can be used by many bots)
    # trading_bots = relationship("UserTradingBot", back_populates="api_credential") # Uncomment if back_populates is set in UserTradingBot

    def __repr__(self):
        return f"<UserApiCredential(id={self.credential_id}, user_id={self.user_id}, service='{self.service_name}', name='{self.credential_name}')>"


class UserTradingBot(UserConfigsBase):
    __tablename__ = 'user_trading_bots'

    bot_id = Column(Integer, primary_key=True, autoincrement=True, comment='Primary key for the bot configuration')
    user_id = Column(Integer, nullable=False, index=True, comment='Foreign key referencing the main users table ID (in userdb)')
    bot_name = Column(String(255), nullable=False, comment='User-defined name for this bot')
    
    credential_id = Column(Integer, ForeignKey('user_api_credentials.credential_id'), nullable=False, index=True, comment='Which API credential set this bot uses')
    
    strategy_name = Column(String(100), nullable=False, comment='Identifier/key of the trading strategy to use')
    strategy_params_json = Column(JSON, nullable=False, comment='JSON object containing parameters for the strategy')
    
    market = Column(String(100), nullable=False, comment='Market category (e.g., crypto, us_equity)')
    symbol = Column(String(100), nullable=False, comment='Trading symbol (e.g., BTC/USDT, AAPL)')
    timeframe = Column(String(20), nullable=False, comment='Timeframe for the strategy (e.g., 1h, 5m)')
    
    is_active = Column(Boolean, nullable=False, default=False, index=True, comment='Whether the bot is currently configured to be active/running')
    status_message = Column(String(512), nullable=True, comment='Last known status or error message from the bot')
    
    created_at = Column(TIMESTAMP, server_default=func.now(), comment='Timestamp of creation')
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), comment='Timestamp of last update')

    # Relationships
    api_credential = relationship("UserApiCredential") #, back_populates="trading_bots") # Creates UserTradingBot.api_credential
    trade_logs = relationship("TradeLog", back_populates="trading_bot", cascade="all, delete-orphan") # If a bot is deleted, its trade logs are also deleted

    def __repr__(self):
        return f"<UserTradingBot(id={self.bot_id}, name='{self.bot_name}', user_id={self.user_id}, symbol='{self.symbol}')>"


class TradeLog(UserConfigsBase):
    __tablename__ = 'trade_logs'

    trade_log_id = Column(Integer, primary_key=True, autoincrement=True, comment='Primary key for the trade log entry')
    # --- NEW/UPDATED COLUMNS ---
    user_id = Column(Integer, nullable=False, index=True, comment='User who owns the bot/placed the manual trade')
    bot_id = Column(Integer, ForeignKey('user_trading_bots.bot_id'), nullable=True, index=True, comment='Foreign key to user_trading_bots. Null for manual trades.')
    credential_id = Column(Integer, ForeignKey('user_api_credentials.credential_id'), nullable=False, index=True, comment='Which API credential was used for this trade/action')
    # --- END NEW/UPDATED COLUMNS ---

    exchange_order_id = Column(String(255), index=True, nullable=True, comment='Order ID from the exchange')
    client_order_id = Column(String(255), nullable=True, comment='Client-generated order ID, if any')
    
    timestamp = Column(TIMESTAMP, nullable=False, server_default=func.now(), comment='Timestamp of the log event (e.g., order placement, fill)')
    symbol = Column(String(100), nullable=False, comment='Trading symbol')
    order_type = Column(String(50), nullable=False, comment='Type of order (market, limit, etc.)')
    side = Column(String(10), nullable=False, comment='Order side (buy, sell)')
    
    price = Column(DECIMAL(20, 8), nullable=True, comment='Intended or average filled price')
    quantity = Column(DECIMAL(20, 8), nullable=True, comment='Order quantity') # Requested or filled based on context
    
    status = Column(String(50), nullable=False, comment='Status of the order or trade event (e.g., PLACED, FILLED, CANCELLED, ERROR)')
    
    commission_amount = Column(DECIMAL(20, 8), nullable=True, comment='Fee amount')
    commission_asset = Column(String(20), nullable=True, comment='Currency of the fee')
    
    notes = Column(Text, nullable=True, comment='Additional notes, error messages, or strategy context')

    # Relationships
    trading_bot = relationship("UserTradingBot", back_populates="trade_logs")
    # api_credential_used = relationship("UserApiCredential") # If you want to navigate from TradeLog to UserApiCredential

    def __repr__(self):
        return f"<TradeLog(id={self.trade_log_id}, order_id='{self.exchange_order_id}', symbol='{self.symbol}', status='{self.status}')>"


class UserChartLayout(UserConfigsBase):
    __tablename__ = 'user_chart_layouts'

    layout_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    layout_name = Column(String(255), nullable=False)
    market = Column(String(100), nullable=False)
    provider = Column(String(100), nullable=False)
    symbol = Column(String(100), nullable=False)
    timeframe = Column(String(20), nullable=False)
    layout_config_json = Column(JSON, nullable=False, comment='JSON string or object storing chart layout config')
    is_default_for_instrument = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint('user_id', 'layout_name', name='uk_user_layout_name'),)


class UserGeneralPreference(UserConfigsBase):
    __tablename__ = 'user_general_preferences'

    user_id = Column(Integer, primary_key=True) # User ID acts as PK, one row per user
    ui_theme = Column(String(50), nullable=False, default='light')
    default_chart_market = Column(String(100), nullable=True)
    default_chart_provider = Column(String(100), nullable=True)
    default_chart_timeframe = Column(String(20), nullable=True)
    other_settings_json = Column(JSON, nullable=True, comment='For miscellaneous key-value user settings')
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class UserIndicatorPreset(UserConfigsBase):
    __tablename__ = 'user_indicator_presets'

    preset_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    indicator_type = Column(String(50), nullable=False, comment='e.g., SMA, EMA, RSI, MACD')
    preset_name = Column(String(255), nullable=False)
    params_json = Column(JSON, nullable=False, comment='Parameters for the indicator (e.g., periods, source)')
    visual_config_json = Column(JSON, nullable=True, comment='Visual settings (e.g., color, line style)')
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint('user_id', 'indicator_type', 'preset_name', name='uk_user_indicator_preset_name'),)