# trading/bot.py

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Type, Union
from quart import Config # For app_config type hint
from sqlalchemy import select

# Import necessary components from your project
from plugins.base import (
    MarketPlugin,
    OHLCVBar,
    Order,
    Position,
    # Balance, # Not directly used in this file, but strategy might use it
    InstrumentTradingDetails,
    PluginError,
    AuthenticationPluginError, # [cite: 230]
    NetworkPluginError, # [cite: 230]
    PluginFeatureNotSupportedError # Added this for completeness
)
from .strategies.base_strategy import TradingStrategyBase, Signal, SignalAction, StrategyMarketData

from app_extensions.user_configs_db_setup import user_configs_db_session_scope 
from models.user_config_models import TradeLog, UserTradingBot 

from services.market_service import MarketService # [cite: 230]
from utils.timeframes import _parse_timeframe_str # For _get_timeframe_duration_seconds

logger = logging.getLogger(__name__) # Or "TradingBot"

class TradingBot:
    """
    Represents an automated trading bot that executes a specific trading strategy
    using a given market plugin for a particular symbol and timeframe.

    The bot's lifecycle (start, stop, run loop) is managed here. It fetches
    market data, passes it to its strategy for analysis, executes generated
    signals, and logs trading actions.
    """

    def __init__(
        self,
        user_id: int, # [cite: 231]
        bot_config_id: int, # The ID from the UserTradingBotModel table [cite: 232]
        bot_name: str, # [cite: 231]
        credential_id_for_logging: int, # *** NEWLY ADDED: For accurate trade logging ***
        strategy_instance: TradingStrategyBase, # [cite: 231]
        market_plugin: MarketPlugin, # [cite: 231]
        symbol: str, # [cite: 231]
        timeframe: str, # [cite: 231]
        app_config: Config, # For accessing global app settings [cite: 231]
        market_service: MarketService # For fetching data [cite: 231]
    ):
        """
        Initializes a TradingBot instance.

        Args:
            user_id: The ID of the user who owns this bot.
            bot_config_id: The database ID of this bot's configuration.
            bot_name: A user-defined name for the bot.
            credential_id_for_logging: The ID of the UserApiCredential this bot is
                                       configured to use. Essential for logging.
            strategy_instance: An initialized instance of a TradingStrategyBase subclass.
            market_plugin: An initialized and configured MarketPlugin instance.
            symbol: The trading symbol the bot will operate on (e.g., "BTC/USDT").
            timeframe: The timeframe the bot will operate on (e.g., "1h", "5m").
            app_config: The application's configuration object.
            market_service: The application's MarketService instance.
        """
        self.user_id = user_id # [cite: 231]
        self.bot_config_id = bot_config_id # [cite: 232]
        self.bot_name = bot_name # [cite: 232]
        
        # *** Store the credential_id used by this bot instance ***
        self.credential_id_used = credential_id_for_logging
        
        self.strategy = strategy_instance # [cite: 232]
        self.plugin = market_plugin # [cite: 232]
        self.symbol = symbol # [cite: 232]
        self.timeframe = timeframe # [cite: 232]
        self._app_config = app_config # [cite: 232]
        self._market_service = market_service # [cite: 232]

        self.is_running: bool = False # [cite: 232]
        self._run_task: Optional[asyncio.Task] = None # [cite: 232]
        self.current_status_message: str = "Initialized" # [cite: 233]
        self.last_error_message: Optional[str] = None # [cite: 233]
        self.last_analysis_time: Optional[float] = None # Timestamp of the last strategy analysis # [cite: 233]
        
        # Trade logging can be enabled/disabled via app config
        self.trade_log_enabled: bool = self._app_config.get("BOT_TRADE_LOGGING_ENABLED", True) # [cite: 233]

        # Pass current symbol and timeframe context to the strategy instance
        self.strategy.current_symbol = symbol # [cite: 233]
        self.strategy.current_timeframe = timeframe # [cite: 233]

        self.log_prefix = f"Bot '{self.bot_name}' (BotCfgID:{self.bot_config_id}, User:{self.user_id}, CredID:{self.credential_id_used}, {self.plugin.provider_id}/{self.symbol}@{self.timeframe}):" # [cite: 233]
        logger.info(f"{self.log_prefix} Instance created and initialized.") # [cite: 233]

    async def start(self):
        """
        Starts the bot's main operational loop in a new asyncio Task.
        Updates the bot's status in the database to reflect it's starting.
        """
        if self.is_running and self._run_task and not self._run_task.done(): # [cite: 234]
            logger.warning(f"{self.log_prefix} Bot is already running. Start command ignored.") # [cite: 234]
            return

        self.is_running = True # [cite: 234]
        self.current_status_message = "Starting..." # [cite: 234]
        # Update DB status asynchronously
        await self._update_bot_status_in_db(is_active=True, message="Bot starting up...") # [cite: 234]
        
        logger.info(f"{self.log_prefix} Starting bot...") # [cite: 234]
        # Create a named task for better debugging and management
        task_name = f"TradingBotLoop_{self.bot_config_id}_{self.bot_name}"
        self._run_task = asyncio.create_task(self._run_loop(), name=task_name) # [cite: 234]
        
    async def stop(self, reason: str = "Manual stop request"):
        """
        Stops the bot's main operational loop.
        Cancels the running asyncio Task and updates the bot's status in the database.

        Args:
            reason: A string indicating why the bot is being stopped.
        """
        if not self.is_running: # [cite: 235]
            logger.warning(f"{self.log_prefix} Bot is already stopped. Stop command ignored.") # [cite: 235]
            return

        logger.info(f"{self.log_prefix} Stopping bot... Reason: {reason}") # [cite: 235]
        self.is_running = False # Signal the loop to terminate # [cite: 235]
        
        if self._run_task:
            try:
                if not self._run_task.done():
                    self._run_task.cancel() # [cite: 236]
                    await self._run_task # Wait for the task to actually finish/handle cancellation # [cite: 236]
            except asyncio.CancelledError:
                logger.info(f"{self.log_prefix} Run loop task successfully cancelled.") # [cite: 236]
            except Exception as e: # Log any other errors during task cancellation
                logger.error(f"{self.log_prefix} Error encountered during run loop task cancellation: {e}", exc_info=True) # [cite: 236]
        self._run_task = None # [cite: 236]
 
        self.current_status_message = f"Stopped: {reason}" # [cite: 237]
        await self._update_bot_status_in_db(is_active=False, message=self.current_status_message) # [cite: 237]
        logger.info(f"{self.log_prefix} Bot stopped successfully.") # [cite: 237]

    async def _run_loop(self):
        """
        The main operational loop of the trading bot.

        This loop continuously:
        1. Fetches the latest market data (OHLCV, instrument details).
        2. Fetches current account balance and open positions/orders.
        3. Calls the strategy's `analyze` method to get trading signals.
        4. Executes any generated signals by placing or managing orders.
        5. Handles errors and retries (implicitly via sleep or explicitly if designed).
        6. Sleeps for an appropriate duration based on the bot's timeframe.
        The loop terminates if `self.is_running` becomes False.
        """
        logger.info(f"{self.log_prefix} Bot run loop started.")
        try:
            # Fetch initial instrument details. If this fails, the bot cannot operate safely.
            instrument_details: Optional[InstrumentTradingDetails] = await self.plugin.get_instrument_trading_details(
                self.symbol, 
                market_type=self.strategy.params.get("market_type_for_instrument", 'spot') # Strategy can define market type
            ) # [cite: 237]
            if not instrument_details:
                status_msg = f"Failed to fetch critical instrument details for {self.symbol}. Bot cannot start." # [cite: 237, 238]
                logger.error(f"{self.log_prefix} {status_msg}") # [cite: 238]
                await self.stop(reason=status_msg) # Call async stop # [cite: 238]
                return

            self.current_status_message = "Running - Awaiting first cycle" # [cite: 238]
            await self._update_bot_status_in_db(message="Bot run loop active and monitoring.") # [cite: 238]

            while self.is_running: # [cite: 239]
                loop_start_time_monotonic = time.monotonic() # For calculating processing time
                try:
                    logger.debug(f"{self.log_prefix} Starting new analysis cycle.") # [cite: 239]
                    self.last_analysis_time = time.time() # Record current time for analysis [cite: 239]
                    
                    # Determine how many historical bars the strategy needs
                    num_bars_needed = self.strategy.params.get("history_bars_needed", 200) # [cite: 240]
                    
                    # Fetch OHLCV data using MarketService (which uses DataOrchestrator)
                    ohlcv_bars: List[OHLCVBar] = await self._market_service.fetch_ohlcv(
                        market=self.plugin.supported_markets[0] if self.plugin.supported_markets else "unknown_market_category",  # [cite: 240]
                        provider=self.plugin.provider_id, # [cite: 241]
                        symbol=self.symbol, # [cite: 241]
                        timeframe=self.timeframe, # [cite: 241]
                        limit=num_bars_needed, # Fetch enough for the strategy # [cite: 241]
                        user_id=str(self.user_id) # Pass user_id for MarketService context if needed for plugin auth [cite: 241]
                    ) # [cite: 242]
                    
                    if not ohlcv_bars:
                        logger.warning(f"{self.log_prefix} No OHLCV data received for {self.symbol}@{self.timeframe}. Strategy may not be ableto analyze.")
                        # Depending on strategy, it might still proceed or hold.
                    
                    # Prepare market data for the strategy
                    market_data_for_strategy: StrategyMarketData = {
                        "symbol": self.symbol, # [cite: 242]
                        "timeframe": self.timeframe, # [cite: 243]
                        "ohlcv_bars": ohlcv_bars, # [cite: 243]
                        "latest_bar": ohlcv_bars[-1] if ohlcv_bars else None, # [cite: 243]
                        "current_tick": None,  # This bot architecture primarily uses bar data; ticks could be added # [cite: 243]
                        "instrument_details": instrument_details # Pass along the fetched details # [cite: 244]
                    }

                    # Fetch account status (balance, positions, open orders)
                    # These calls are made directly to the plugin instance for this bot.
                    account_balance = await self.plugin.get_account_balance() # [cite: 244]
                    open_positions = await self.plugin.get_open_positions(symbols=[self.symbol]) # [cite: 244]
                    # TODO: Implement fetching open orders if strategy needs it
                    # open_orders: List[Order] = await self.plugin.fetch_open_orders(symbol=self.symbol) 
                    open_orders: List[Order] = [] # Placeholder # [cite: 245]

                    # Get signals from the strategy
                    signals: List[Signal] = await self.strategy.analyze(
                        market_data_for_strategy,
                        account_balance,
                        open_positions, # [cite: 246]
                        open_orders # [cite: 246]
                    )

                    if signals:
                        logger.info(f"{self.log_prefix} Strategy '{self.strategy.strategy_name}' generated {len(signals)} signal(s): {signals}") # [cite: 246]
                        for signal in signals:
                            await self._execute_signal(signal) # Ensure signal execution is awaited # [cite: 247]
                    else:
                        logger.debug(f"{self.log_prefix} No signals generated by strategy in this cycle.") # [cite: 248]
                    
                    self.current_status_message = "Running - Cycle complete" # [cite: 248]
                    self.last_error_message = None # Clear last error on successful cycle [cite: 248]
                    await self._update_bot_status_in_db(message=self.current_status_message)


                except AuthenticationPluginError as e_auth: # [cite: 248]
                    status_msg = f"Authentication Error with plugin {self.plugin.provider_id}: {e_auth}. Bot stopping." # [cite: 249]
                    self.current_status_message = status_msg # [cite: 249, 250]
                    self.last_error_message = status_msg # [cite: 250]
                    logger.error(f"{self.log_prefix} {status_msg}", exc_info=True) # [cite: 250]
                    await self.stop(reason="Authentication Error") # Call async stop # [cite: 250]
                    break # Exit the run loop
                except PluginFeatureNotSupportedError as e_feat: # [cite: 251]
                    status_msg = f"Plugin Feature Not Supported by {self.plugin.provider_id}: {e_feat}. Bot stopping." # [cite: 251, 252]
                    self.current_status_message = status_msg # [cite: 252]
                    self.last_error_message = status_msg # [cite: 252]
                    logger.error(f"{self.log_prefix} {status_msg}", exc_info=True) # [cite: 252]
                    await self.stop(reason="Plugin Feature Not Supported") # Call async stop # [cite: 252]
                    break # Exit the run loop
                except PluginError as e_plugin: # Catch other specific plugin errors # [cite: 253]
                    status_msg = f"Plugin Error with {self.plugin.provider_id}: {e_plugin}. Retrying after delay." # [cite: 253, 254]
                    self.current_status_message = status_msg # [cite: 254]
                    self.last_error_message = status_msg # [cite: 254]
                    logger.error(f"{self.log_prefix} {status_msg}", exc_info=True) # [cite: 254]
                    await self._update_bot_status_in_db(message=self.current_status_message) # Update status before sleep
                except Exception as e_loop: # Catch any other unexpected errors in the loop
                    status_msg = f"Unexpected Error in run cycle: {e_loop}. Retrying after delay." # [cite: 254, 255]
                    self.current_status_message = status_msg # [cite: 255]
                    self.last_error_message = status_msg # [cite: 255]
                    logger.error(f"{self.log_prefix} {status_msg}", exc_info=True) # [cite: 255]
                    await self._update_bot_status_in_db(message=self.current_status_message) # Update status before sleep
                
                # Calculate sleep duration until the next bar/analysis cycle
                timeframe_duration_seconds = self._get_timeframe_duration_seconds() # [cite: 255]
                processing_time_seconds = time.monotonic() - loop_start_time_monotonic # [cite: 256]
                
                sleep_duration_seconds = max(0, timeframe_duration_seconds - processing_time_seconds) # [cite: 256]
                
                logger.debug(f"{self.log_prefix} Cycle processing took {processing_time_seconds:.2f}s. Sleeping for {sleep_duration_seconds:.2f}s before next cycle.") # [cite: 256]
                if sleep_duration_seconds > 0:
                    try:
                        await asyncio.sleep(sleep_duration_seconds) # [cite: 256]
                    except asyncio.CancelledError:
                        logger.info(f"{self.log_prefix} Sleep interrupted due to task cancellation.")
                        break # Exit loop if cancelled during sleep

        except asyncio.CancelledError:
            logger.info(f"{self.log_prefix} Bot run loop was cancelled.") # [cite: 257]
        except Exception as e_critical_run: # Catch critical errors that might occur outside the inner try-except
            status_msg = f"Critical error in bot run loop: {e_critical_run}. Bot stopping." # [cite: 257, 258]
            self.current_status_message = status_msg # [cite: 258]
            self.last_error_message = status_msg # [cite: 258]
            logger.critical(f"{self.log_prefix} {status_msg}", exc_info=True) # [cite: 258]
            # Ensure status is updated in DB even on critical exit, if possible
            await self._update_bot_status_in_db(is_active=False, message=self.current_status_message) # [cite: 258]
        finally:
            logger.info(f"{self.log_prefix} Bot run loop ended.") # [cite: 258]
            # Ensure is_running is false if loop terminates for any reason other than explicit stop command
            if self.is_running: # If loop exited unexpectedly while self.is_running was still true
                self.is_running = False
                await self._update_bot_status_in_db(is_active=False, message=self.current_status_message or "Stopped due to loop termination")


    async def _execute_signal(self, signal: Signal):
        """
        Executes a trading signal received from the strategy.
        This involves calling the appropriate method on the market plugin
        (e.g., place_order, cancel_order).

        Args:
            signal: The Signal object containing the action to take and its parameters.
        """
        logger.info(f"{self.log_prefix} Executing signal: {signal}") # [cite: 258, 259]
        action = signal.get('action') # [cite: 259]
        # Symbol from signal might override bot's default symbol if strategy supports multi-symbol signals
        symbol_from_signal = signal.get('symbol', self.symbol) # [cite: 259]
        placed_order_response: Optional[Order] = None # To store response for logging

        try:
            if action == SignalAction.BUY or action == SignalAction.SELL:
                order_type = signal.get('order_type', 'market').lower() # [cite: 259]
                amount = signal.get('amount') # [cite: 259]
                price = signal.get('price') # For limit orders # [cite: 260]
                
                if amount is None or amount <= 0:
                    logger.warning(f"{self.log_prefix} Invalid or missing amount ({amount}) for {action} signal. Signal ignored.") # [cite: 260]
                    await self._log_trade(signal, None, "INVALID_SIGNAL_PARAMS", error_message="Invalid amount")
                    return

                # Get exchange-specific parameters from the signal, if any
                order_params = signal.get('params', {}) # [cite: 260]
                
                # Call the plugin to place the order
                placed_order_response = await self.plugin.place_order(
                    symbol=symbol_from_signal, # [cite: 261]
                    order_type=order_type, # [cite: 261]
                    side=action.value.lower(), # e.g., "buy", "sell" from SignalAction enum [cite: 261]
                    amount=amount, # [cite: 262]
                    price=price, # [cite: 262]
                    params=order_params # [cite: 262]
                )
                logger.info(f"{self.log_prefix} Order placement attempt for {action} {amount} {symbol_from_signal} returned: {placed_order_response}") # [cite: 262]
                # Log after the attempt, using the actual response
                await self._log_trade(signal, placed_order_response, "EXECUTED_ORDER" if placed_order_response and placed_order_response.get('id') else "EXECUTION_ATTEMPT_FAILED") # [cite: 263]

            elif action == SignalAction.CLOSE_POSITION:
                # This requires careful implementation:
                # 1. Identify the position to close (e.g., from signal.get('position_to_modify')).
                # 2. Determine side and amount for the closing order (opposite to position).
                # 3. Place a market or limit order to close.
                position_to_close = signal.get('position_to_modify') # [cite: 263]
                logger.warning(f"{self.log_prefix} CLOSE_POSITION signal received, but full implementation for arbitrary positions is complex and needs careful handling of position data. Signal: {position_to_close}") # [cite: 263]
                # Simplified: If strategy provides amount and it's just a sell/buy to flatten
                if signal.get('amount') and signal.get('order_type'): # If signal is specific enough to be a simple order
                    close_side = "sell" if signal.get('amount', 0) > 0 else "buy" # Assuming positive amount for long, negative for short
                    close_amount = abs(signal.get('amount', 0))
                    if close_amount > 0:
                        placed_order_response = await self.plugin.place_order(
                            symbol=symbol_from_signal,
                            order_type=signal.get('order_type', 'market'),
                            side=close_side,
                            amount=close_amount,
                            price=signal.get('price'), # if limit close
                            params=signal.get('params', {})
                        )
                        await self._log_trade(signal, placed_order_response, "EXECUTED_CLOSE_ORDER")
                    else:
                        await self._log_trade(signal, None, "INVALID_CLOSE_ORDER_AMOUNT", error_message="Close position signal with zero amount.")
                else:
                    await self._log_trade(signal, None, "CLOSE_POSITION_NOT_IMPLEMENTED", error_message="Generic close position not fully implemented.")
            
            elif action == SignalAction.CANCEL_ORDER:
                order_to_cancel_details = signal.get('order_to_cancel') # [cite: 264]
                if order_to_cancel_details and order_to_cancel_details.get('id'):
                    order_id_to_cancel = order_to_cancel_details['id']
                    symbol_for_cancel = order_to_cancel_details.get('symbol', symbol_from_signal)
                    cancel_result = await self.plugin.cancel_order(order_id_to_cancel, symbol=symbol_for_cancel) # [cite: 264]
                    logger.info(f"{self.log_prefix} Order cancellation attempt for ID {order_id_to_cancel} (Symbol: {symbol_for_cancel}) result: {cancel_result}") # [cite: 264]
                    await self._log_trade(signal, cancel_result, "CANCELLED_ORDER_ATTEMPT") # [cite: 265]
                else:
                    logger.warning(f"{self.log_prefix} Cannot cancel order: Missing order ID or details in signal. Signal: {signal}") # [cite: 265]
                    await self._log_trade(signal, None, "INVALID_CANCEL_ORDER_SIGNAL", error_message="Missing order ID for cancellation.")

            # Add other signal actions (HOLD, etc.) if they require plugin interaction
            elif action == SignalAction.HOLD:
                logger.debug(f"{self.log_prefix} HOLD signal received. No action taken with plugin.")
                # Optionally log HOLD signals if verbose logging is desired
                # await self._log_trade(signal, None, "HOLD_SIGNAL")

        except PluginFeatureNotSupportedError as e_feat:
            msg = f"Action {action} on {symbol_from_signal} not supported by plugin {self.plugin.provider_id}: {e_feat}" # [cite: 265]
            logger.error(f"{self.log_prefix} {msg}") # [cite: 265]
            self.last_error_message = msg # [cite: 266]
            await self._update_bot_status_in_db(message=msg) # Update status with error # [cite: 266]
            await self._log_trade(signal, None, "EXECUTION_FEATURE_NOT_SUPPORTED", error_message=str(e_feat))
        except (PluginError, ValueError) as e_plugin_val: # Catch plugin errors or value errors from inputs
            # ValueError could be from invalid numbers for amount/price if not caught earlier
            msg = f"Error executing {action} signal for {symbol_from_signal}: {e_plugin_val}" # [cite: 266]
            logger.error(f"{self.log_prefix} {msg}", exc_info=True) # [cite: 266]
            self.last_error_message = msg # [cite: 266]
            await self._update_bot_status_in_db(message=msg) # Update status # [cite: 267]
            await self._log_trade(signal, None, "EXECUTION_ERROR", error_message=str(e_plugin_val)) # [cite: 267]
        except Exception as e_exec: # Catch any other unexpected errors during signal execution
            msg = f"Unexpected critical error executing {action} signal for {symbol_from_signal}: {e_exec}" # [cite: 267]
            logger.critical(f"{self.log_prefix} {msg}", exc_info=True) # [cite: 267]
            self.last_error_message = msg # [cite: 267]
            await self._update_bot_status_in_db(message=f"Critical error during signal execution: {str(e_exec)[:100]}") # Update status # [cite: 267]
            await self._log_trade(signal, None, "CRITICAL_EXECUTION_ERROR", error_message=str(e_exec)) # [cite: 268]


    async def _log_trade(
        self, 
        signal: Signal, 
        order_response: Optional[Union[Order, Dict[str, Any]]], # Can be Order TypedDict or raw dict from plugin
        event_type: str, 
        error_message: Optional[str] = None
    ):
        """
        Logs a trade action, an attempted trade, or a signal-related event to the database.

        Args:
            signal: The original Signal object from the strategy.
            order_response: The response from the plugin after attempting an order action
                            (e.g., place_order, cancel_order). This can be None if the
                            action did not involve an order or if it failed before response.
            event_type: A string categorizing the event (e.g., "EXECUTED_ORDER",
                        "EXECUTION_ERROR", "INVALID_SIGNAL_PARAMS").
            error_message: An optional error message if the event represents a failure.
        """
        if not self.trade_log_enabled: # [cite: 269]
            return

        log_prefix_trade = f"{self.log_prefix} LogTrade:" # [cite: 269]
        try:
            # Ensure we use the credential_id this bot instance was configured with
            if self.credential_id_used is None: # Should have been set in __init__
                logger.error(f"{log_prefix_trade} CRITICAL: credential_id_used is None. Cannot log trade accurately. Signal: {signal}")
                return

            # Prepare data for TradeLog entry
            # Extract details from order_response if it's a dictionary (common for CCXT or direct plugin returns)
            exchange_id = None
            client_id = None
            reported_price = None
            reported_amount = None
            reported_status = event_type # Default to event_type if no specific status from response
            fee_cost = None
            fee_currency = None

            if isinstance(order_response, dict): # Check if it's a dict-like response
                exchange_id = order_response.get('id') # [cite: 271]
                client_id = order_response.get('clientOrderId') or order_response.get('client_order_id') # [cite: 272]
                # Price and amount might be in different fields depending on the plugin/exchange structure
                reported_price = order_response.get('price')
                if reported_price is None: reported_price = order_response.get('average') # Average fill price
                
                reported_amount = order_response.get('amount')
                if reported_amount is None: reported_amount = order_response.get('filled') # Filled amount

                reported_status = order_response.get('status', event_type) # [cite: 273]
                
                fee_info = order_response.get('fee') # CCXT style fee object
                if isinstance(fee_info, dict):
                    fee_cost = fee_info.get('cost') # [cite: 274]
                    fee_currency = fee_info.get('currency') # [cite: 274]
                elif isinstance(order_response.get('fees'), list) and order_response['fees']: # Alternative fee structure
                    primary_fee = order_response['fees'][0]
                    if isinstance(primary_fee, dict):
                        fee_cost = primary_fee.get('cost')
                        fee_currency = primary_fee.get('currency')
            
            final_notes = f"Strategy: {signal.get('strategy_name', self.strategy.strategy_key)}. SignalComment: {signal.get('comment', 'N/A')}." # [cite: 273]
            if error_message:
                final_notes += f" Error: {error_message}" # [cite: 274]

            async with user_configs_db_session_scope() as session: # Use async session scope for DB operations # [cite: 269]
                log_entry = TradeLog(
                    user_id=self.user_id, # [cite: 270]
                    bot_id=self.bot_config_id, # [cite: 270]
                    credential_id=self.credential_id_used, # *** Use the stored credential_id *** [cite: 271]
                    exchange_order_id=exchange_id, # [cite: 271]
                    client_order_id=signal.get('client_order_id', client_id), # Prefer signal's, fallback to response's # [cite: 272]
                    symbol=signal.get('symbol', self.symbol), # [cite: 272]
                    order_type=signal.get('order_type', 'unknown').lower(), # [cite: 272]
                    side=signal.get('action', SignalAction.HOLD).value.lower(), # [cite: 272]
                    price=signal.get('price') if signal.get('price') is not None else reported_price, # [cite: 273]
                    quantity=signal.get('amount') if signal.get('amount') is not None else reported_amount, # [cite: 273]
                    status=reported_status, # [cite: 273]
                    notes=final_notes.strip(), # [cite: 274]
                    commission_amount=fee_cost, # [cite: 274]
                    commission_asset=fee_currency, # [cite: 274]
                )
                session.add(log_entry)
                # Commit is handled by the user_configs_db_session_scope
                logger.info(f"{log_prefix_trade} Trade event '{event_type}' logged for symbol {log_entry.symbol}, Order ID: {exchange_id or 'N/A'}.") # [cite: 275]
        except Exception as e:
            # Rollback handled by scope
            logger.error(f"{log_prefix_trade} Failed to log trade event due to an unexpected error: {e}", exc_info=True) # [cite: 275]

    async def _update_bot_status_in_db(self, is_active: Optional[bool] = None, message: Optional[str] = None):
        """
        Updates the bot's status (is_active flag and status_message)
        in the `user_trading_bots` table asynchronously.

        Args:
            is_active: If provided, sets the bot's `is_active` state.
            message: If provided, updates the bot's `status_message`.
        """
        log_prefix_db_update = f"{self.log_prefix} UpdateDBStatus:" # [cite: 276]
        try:
            async with user_configs_db_session_scope() as session: # Use async session scope # [cite: 276]
                # Use select() and then update the fetched object, or use update() statement
                stmt = select(UserTradingBot).where(UserTradingBot.bot_id == self.bot_config_id) # [cite: 276]
                result = await session.execute(stmt) # [cite: 276]
                bot_db_record = result.scalars().first() # [cite: 277]
                
                if bot_db_record:
                    updated = False
                    if is_active is not None and bot_db_record.is_active != is_active:
                        bot_db_record.is_active = is_active # [cite: 277]
                        updated = True
                    if message and bot_db_record.status_message != message[:512]: # Check if message changed
                        bot_db_record.status_message = message[:512] # Ensure message fits column size # [cite: 278]
                        updated = True
                    
                    if updated:
                        # Commit is handled by the user_configs_db_session_scope
                        logger.debug(f"{log_prefix_db_update} Bot status updated in DB: Active={bot_db_record.is_active}, Msg='{bot_db_record.status_message}'") # [cite: 278]
                    else:
                        logger.debug(f"{log_prefix_db_update} Bot status in DB unchanged (Active: {is_active}, Msg: '{message}').")
                else:
                    logger.warning(f"{log_prefix_db_update} Bot record with ID {self.bot_config_id} not found in DB. Cannot update status.") # [cite: 279]
        except Exception as e:
            # Rollback handled by scope
            logger.error(f"{log_prefix_db_update} Failed to update bot status in DB: {e}", exc_info=True) # [cite: 279]
            
    def _get_timeframe_duration_seconds(self) -> int:
        """
        Calculates the duration of the bot's configured timeframe in seconds.
        Uses `utils.timeframes._parse_timeframe_str`.

        Returns:
            The duration in seconds, or defaults to 60 seconds if parsing fails.
        """
        try:
            _, _, period_ms = _parse_timeframe_str(self.timeframe) # _parse_timeframe_str is from utils.timeframes
            if period_ms > 0:
                return period_ms // 1000
            else:
                logger.warning(f"{self.log_prefix} Parsed timeframe '{self.timeframe}' resulted in non-positive milliseconds ({period_ms}). Defaulting sleep to 60s.")
                return 60
        except ValueError: # If _parse_timeframe_str raises ValueError for invalid format
            logger.warning(f"{self.log_prefix} Unknown timeframe format '{self.timeframe}' for sleep calculation. Defaulting to 60s.") # [cite: 280, 281]
            return 60 # Default to 60 seconds if timeframe string is unknown [cite: 281]

    def get_status_summary(self) -> Dict[str, Any]:
        """
        Provides a summary of the bot's current status and configuration.

        Returns:
            A dictionary containing key details about the bot.
        """
        return {
            "user_id": self.user_id,
            "bot_id": self.bot_config_id, # [cite: 281]
            "bot_name": self.bot_name, # [cite: 281]
            "credential_id_used": self.credential_id_used, # Expose which credential set is in use
            "provider_id": self.plugin.provider_id,
            "symbol": self.symbol, # [cite: 281]
            "timeframe": self.timeframe, # [cite: 281]
            "is_running": self.is_running, # [cite: 281]
            "status_message": self.current_status_message, # [cite: 282]
            "last_error": self.last_error_message, # [cite: 282]
            "last_analysis_timestamp": self.last_analysis_time, # [cite: 282]
            "strategy_details": self.strategy.get_details() if self.strategy else None, # [cite: 282]
        }