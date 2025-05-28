# trading/bot_manager_service.py

import asyncio
import logging
from typing import Any, Dict, List, Optional, Type

from quart import Config # For app_config type hint
from sqlalchemy import select

# Project-specific imports
from trading.bot import TradingBot 
from trading.strategies.base_strategy import TradingStrategyBase
# Example strategy, you might have a more dynamic way to load strategies
from trading.strategies.predefined.sma_crossover_strategy import SMACrossoverStrategy 

from services.market_service import MarketService
from app_extensions.user_configs_db_setup import user_configs_db_session_scope 
from models.user_config_models import UserTradingBot as UserTradingBotModel, UserApiCredential

logger = logging.getLogger(__name__) # Or "BotManagerService"

class BotManagerService:
    """
    Manages the lifecycle of all active trading bots for all users.
    It loads bot configurations from the database, instantiates them with
    the necessary components (strategy, market plugin), and handles
    starting, stopping, and monitoring their runtime status.
    """

    def __init__(self, app_config: Config, market_service: MarketService):
        """
        Initializes the BotManagerService.

        Args:
            app_config: The application's configuration object.
            market_service: The main MarketService instance for accessing plugins.
        """
        self._app_config = app_config
        self._market_service = market_service
        self.active_bots: Dict[int, TradingBot] = {} # Stores active TradingBot instances, keyed by bot_config_id
        self._lock = asyncio.Lock() # Protects concurrent access to self.active_bots
        logger.info("BotManagerService initialized.")

    def _get_strategy_instance(self, strategy_name: str, strategy_params: Dict[str, Any]) -> Optional[TradingStrategyBase]:
        """
        Instantiates a trading strategy based on its name and parameters.

        Args:
            strategy_name: The unique key or name of the strategy.
            strategy_params: A dictionary of parameters for initializing the strategy.

        Returns:
            An instance of a TradingStrategyBase subclass, or None if the
            strategy_name is not recognized or initialization fails.
        """
        normalized_strategy_name = strategy_name.lower().strip()
        # In a more advanced system, this might involve dynamic loading or a registry of strategies.
        if normalized_strategy_name == SMACrossoverStrategy.strategy_key.lower(): #
            try:
                return SMACrossoverStrategy(params=strategy_params)
            except ValueError as e:
                logger.error(f"Failed to initialize {SMACrossoverStrategy.strategy_name} with params {strategy_params}: {e}")
                return None
        # Add other strategies here
        # elif normalized_strategy_name == "another_strategy_key":
        #     return AnotherStrategy(params=strategy_params)
        
        logger.warning(f"Strategy loader: Strategy name '{strategy_name}' not recognized.") #
        return None

    async def _update_bot_db_status(self, bot_config_id: int, is_active: Optional[bool], message: str):
        """
        Helper to update a bot's status (is_active and status_message)
        in the UserTradingBotModel table in the database.

        Args:
            bot_config_id: The database ID of the bot configuration.
            is_active: The new active status to set. If None, is_active is not updated.
            message: The status message to set.
        """
        log_prefix = f"BotManagerService DBUpdate (BotID:{bot_config_id}):"
        try:
            async with user_configs_db_session_scope() as session:
                stmt = select(UserTradingBotModel).where(UserTradingBotModel.bot_id == bot_config_id)
                result = await session.execute(stmt) #
                bot_db_record = result.scalars().first() #
                
                if bot_db_record:
                    if is_active is not None: # Only update if a value is provided
                        bot_db_record.is_active = is_active #
                    bot_db_record.status_message = message[:512] # Ensure message fits DB column size #
                    # Commit is handled by the async_session_scope context manager
                    logger.debug(f"{log_prefix} Status updated in DB: Active={is_active}, Msg='{message}'") #
                else:
                    logger.warning(f"{log_prefix} Bot record not found in DB for status update.") #
        except Exception as e:
            # Rollback is handled by the async_session_scope context manager
            logger.error(f"{log_prefix} Failed to update bot status in DB: {e}", exc_info=True) #

    async def _create_bot_from_config(self, bot_config: UserTradingBotModel) -> Optional[TradingBot]:
        """
        Creates and initializes a TradingBot instance from its database configuration.

        This involves:
        1. Instantiating the specified trading strategy.
        2. Fetching the associated API credential details.
        3. Obtaining a configured MarketPlugin instance via MarketService.
        4. Initializing the TradingBot with all necessary components.

        Args:
            bot_config: The UserTradingBotModel ORM object containing the bot's configuration.

        Returns:
            A fully initialized TradingBot instance, or None if creation fails at any step.
        """
        log_prefix = f"BotCreate (DB ID: {bot_config.bot_id}, User: {bot_config.user_id}):"
        logger.info(f"{log_prefix} Attempting to create bot '{bot_config.bot_name}'.") #

        strategy_instance = self._get_strategy_instance(bot_config.strategy_name, bot_config.strategy_params_json)
        if not strategy_instance:
            logger.error(f"{log_prefix} Failed to instantiate strategy '{bot_config.strategy_name}'. Bot will not be created.") #
            await self._update_bot_db_status(bot_config.bot_id, False, f"Error: Unknown or invalid strategy '{bot_config.strategy_name}'.") #
            return None

        api_credential_model: Optional[UserApiCredential] = None
        try:
            # Fetch the API credential associated with this bot config
            async with user_configs_db_session_scope() as session: #
                stmt = (
                    select(UserApiCredential)
                    .where(UserApiCredential.credential_id == bot_config.credential_id) #
                    .where(UserApiCredential.user_id == bot_config.user_id) #
                )
                result = await session.execute(stmt) #
                api_credential_model = result.scalars().first() #
            
            if not api_credential_model:
                logger.error(f"{log_prefix} API Credential ID {bot_config.credential_id} not found or not owned by user {bot_config.user_id}. Bot will not be created.") #
                await self._update_bot_db_status(bot_config.bot_id, False, "Error: Associated API credential not found or invalid.") #
                return None
            
            # Get the market plugin instance from MarketService.
            # MarketService handles decryption of credentials if needed by the plugin.
            market_plugin_instance = await self._market_service.get_plugin_instance(
                market=bot_config.market, 
                provider=api_credential_model.service_name, # Use provider name from the credential
                user_id=str(bot_config.user_id), # Pass user_id for MarketService's credential fetching
                is_testnet_override=api_credential_model.is_testnet # Use testnet status from credential
            ) #
            if not market_plugin_instance:
                logger.error(f"{log_prefix} Failed to get plugin instance for {bot_config.market}/{api_credential_model.service_name}. Bot will not be created.") #
                await self._update_bot_db_status(bot_config.bot_id, False, "Error: Could not initialize market plugin for trading.") #
                return None

            # *** MODIFICATION: Pass credential_id_for_logging to TradingBot constructor ***
            bot = TradingBot(
                user_id=bot_config.user_id, #
                bot_config_id=bot_config.bot_id, #
                bot_name=bot_config.bot_name, #
                credential_id_for_logging=api_credential_model.credential_id, # *** NEWLY ADDED ***
                strategy_instance=strategy_instance, #
                market_plugin=market_plugin_instance, #
                symbol=bot_config.symbol, #
                timeframe=bot_config.timeframe, #
                app_config=self._app_config, #
                market_service=self._market_service #
            )
            logger.info(f"{log_prefix} TradingBot instance created successfully for '{bot_config.bot_name}'.") #
            return bot
            
        except Exception as e: # Catch any other errors during bot creation process
            logger.error(f"{log_prefix} Critical failure during bot instance creation from config: {e}", exc_info=True) #
            await self._update_bot_db_status(bot_config.bot_id, False, f"Error creating bot: {str(e)[:100]}") #
            return None

    async def startup_bots(self):
        """
        Loads all bot configurations marked as active from the database
        and attempts to start them. This is typically called when the
        application starts up.
        """
        logger.info("BotManagerService: Starting up active bots from database...")
        active_bot_configs: List[UserTradingBotModel] = []
        try:
            async with user_configs_db_session_scope() as session:
                stmt = select(UserTradingBotModel).where(UserTradingBotModel.is_active == True) #
                result = await session.execute(stmt) #
                active_bot_configs = list(result.scalars().all()) # Convert to list for iteration #
            
            logger.info(f"BotManagerService: Found {len(active_bot_configs)} active bot configurations to start.") #
            
            for bot_config in active_bot_configs:
                async with self._lock: # Protect access to self.active_bots #
                    if bot_config.bot_id in self.active_bots:
                        logger.warning(f"BotManagerService: Bot ID {bot_config.bot_id} ('{bot_config.bot_name}') is already marked as active in memory. Skipping re-creation.") #
                        continue
                
                # _create_bot_from_config is async and handles its own DB interactions for credential fetching
                bot_instance = await self._create_bot_from_config(bot_config) #
                if bot_instance:
                    async with self._lock:
                        self.active_bots[bot_instance.bot_config_id] = bot_instance #
                    await bot_instance.start() # Start the bot's run loop #
                    logger.info(f"BotManagerService: Successfully started bot '{bot_instance.bot_name}' (ID: {bot_instance.bot_config_id}).") #
                else:
                    logger.error(f"BotManagerService: Failed to create and start bot from config ID {bot_config.bot_id} ('{bot_config.bot_name}'). See previous errors for details.") #
        except Exception as e:
            logger.error(f"BotManagerService: Critical error during startup_bots: {e}", exc_info=True) #
        logger.info("BotManagerService: Finished startup_bots sequence.") #

    async def manage_bot_instance(self, bot_config_id: int, action: str) -> bool:
        """
        Manages a specific bot instance (start or stop) based on its configuration ID.

        Args:
            bot_config_id: The database ID of the bot configuration.
            action: The action to perform ("start" or "stop").

        Returns:
            True if the action was successfully initiated or the bot was already
            in the desired state, False if the action failed or the bot
            configuration was not found.
        """
        log_prefix = f"ManageBotInstance (ID: {bot_config_id}, Action: {action}):"
        logger.info(f"{log_prefix} Request received.") #

        async with self._lock: # Protects modifications to self.active_bots
            existing_bot = self.active_bots.get(bot_config_id)

            if action.lower() == "start":
                if existing_bot and existing_bot.is_running:
                    logger.warning(f"{log_prefix} Bot is already running. No action taken.") #
                    return True # Already in desired state

                # Fetch bot configuration from DB to ensure it's valid and to get details
                bot_config_model: Optional[UserTradingBotModel] = None
                try:
                    async with user_configs_db_session_scope() as session: # New session for this read #
                        stmt = select(UserTradingBotModel).where(UserTradingBotModel.bot_id == bot_config_id) #
                        result = await session.execute(stmt) #
                        bot_config_model = result.scalars().first() #
                    
                    if not bot_config_model:
                        logger.error(f"{log_prefix} Bot configuration with ID {bot_config_id} not found in database.") #
                        return False
                    
                    # If an old instance exists but is not running, clear it before creating a new one
                    if existing_bot and not existing_bot.is_running:
                        logger.info(f"{log_prefix} Removing previous non-running instance before starting anew.")
                        self.active_bots.pop(bot_config_id, None)
                    
                    bot_instance = await self._create_bot_from_config(bot_config_model) #
                    if bot_instance:
                        self.active_bots[bot_config_id] = bot_instance # Add to active_bots under lock #
                        await bot_instance.start() # This will also update DB status #
                        logger.info(f"{log_prefix} Bot '{bot_instance.bot_name}' started successfully.") #
                        return True
                    else:
                        logger.error(f"{log_prefix} Failed to create bot instance for starting. Bot configuration ID: {bot_config_id}.") #
                        # _create_bot_from_config already updates DB status on failure
                        return False
                except Exception as e:
                    logger.error(f"{log_prefix} Exception during bot start process: {e}", exc_info=True) #
                    # Attempt to update DB status if not already done
                    await self._update_bot_db_status(bot_config_id, False, f"Failed to start: {str(e)[:100]}")
                    return False

            elif action.lower() == "stop":
                if not existing_bot:
                    logger.warning(f"{log_prefix} Bot is not currently active in memory. Marking as inactive in DB if it exists.") #
                    # Ensure DB reflects this stopped state, even if it wasn't in active_bots
                    await self._update_bot_db_status(bot_config_id, False, "Stopped via API (was not active in memory).") #
                    return True # Considered successful as the desired state is "stopped"
                
                logger.info(f"{log_prefix} Initiating stop for bot '{existing_bot.bot_name}'.")
                await existing_bot.stop(reason="API request") # This will update DB status #
                if bot_config_id in self.active_bots: 
                     del self.active_bots[bot_config_id] # Remove from active_bots under lock #
                logger.info(f"{log_prefix} Bot stop process completed.") #
                return True
            else:
                logger.error(f"{log_prefix} Unknown action requested: {action}") #
                return False
        
    async def get_bot_status_summary(self, bot_config_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieves the status summary for a specific bot.
        If the bot is active in memory, it gets the live status.
        Otherwise, it fetches the last known status from the database.

        Args:
            bot_config_id: The database ID of the bot configuration.

        Returns:
            A dictionary containing the bot's status summary, or None if
            the bot configuration is not found.
        """
        async with self._lock: # Protects reading self.active_bots #
            bot_instance = self.active_bots.get(bot_config_id)
        
        if bot_instance:
            return bot_instance.get_status_summary() #
        
        # If not in active_bots (i.e., not running), fetch its configuration details from DB
        try:
            async with user_configs_db_session_scope() as session:
                stmt = select(UserTradingBotModel).where(UserTradingBotModel.bot_id == bot_config_id) #
                result = await session.execute(stmt) #
                bot_db_record = result.scalars().first() #
                if bot_db_record:
                    # Construct a summary for an inactive bot
                    return { 
                        "bot_id": bot_db_record.bot_id, #
                        "bot_name": bot_db_record.bot_name, #
                        "symbol": bot_db_record.symbol, #
                        "timeframe": bot_db_record.timeframe, #
                        "is_running": False, # Explicitly false as it's not in active_bots memory #
                        "status_message": bot_db_record.status_message or "Not currently active (inactive).", #
                        "last_error": None, # No live error if not running #
                        "last_analysis_timestamp": None, # No live analysis if not running #
                        "strategy": {"strategy_key": bot_db_record.strategy_name, "current_parameters": bot_db_record.strategy_params_json } #
                    }
        except Exception as e:
            logger.error(f"BotManagerService: Error fetching status for inactive bot ID {bot_config_id} from DB: {e}", exc_info=True) #
        return None # Bot config not found in DB either

    async def get_all_active_bots_summary(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieves status summaries for all bots currently active in memory.
        Optionally filters by user_id.

        Args:
            user_id: If provided, only summaries for bots belonging to this user are returned.

        Returns:
            A list of status summary dictionaries for active bots.
        """
        summaries: List[Dict[str, Any]] = []
        
        # Create a temporary list of bots to summarize to avoid holding the lock during get_status_summary()
        bots_to_summarize_temp: List[TradingBot] = []
        async with self._lock: # Protects reading self.active_bots #
            for bot_instance in self.active_bots.values():
                 if user_id is None or bot_instance.user_id == user_id: #
                    bots_to_summarize_temp.append(bot_instance) #
        
        for bot_instance in bots_to_summarize_temp: # Iterate outside the lock
             summaries.append(bot_instance.get_status_summary()) #
        return summaries

    async def shutdown_all_bots(self):
        """
        Gracefully stops all currently active trading bots.
        This is typically called during application shutdown.
        """
        logger.info(f"BotManagerService: Initiating shutdown for all {len(self.active_bots)} active bots...") #
        
        bots_to_stop_temp: List[TradingBot] = []
        async with self._lock: # Protects access to self.active_bots during iteration #
            for bot in self.active_bots.values():
                if bot.is_running: #
                    bots_to_stop_temp.append(bot) #
        
        if bots_to_stop_temp:
            logger.info(f"BotManagerService: Attempting to stop {len(bots_to_stop_temp)} running bots.")
            # Stop tasks are awaited concurrently
            stop_tasks = [bot.stop(reason="Application shutdown") for bot in bots_to_stop_temp] #
            results = await asyncio.gather(*stop_tasks, return_exceptions=True) #
            for i, result in enumerate(results):
                bot_name_for_log = bots_to_stop_temp[i].bot_name if i < len(bots_to_stop_temp) else 'Unknown Bot'
                if isinstance(result, Exception):
                    logger.error(f"BotManagerService: Error stopping bot '{bot_name_for_log}' during shutdown: {result}", exc_info=True) #
                else:
                    logger.info(f"BotManagerService: Bot '{bot_name_for_log}' successfully processed for stop.")


        async with self._lock: # Final clear of the active_bots dictionary
            self.active_bots.clear() #
        logger.info("BotManagerService: All active bots processed for shutdown and active_bots list cleared.") #