# blueprints/trading_bot.py

import logging
from quart import Blueprint, request, g, current_app
from sqlalchemy import select # Import select
from sqlalchemy.exc import IntegrityError
import json 

from utils.response import make_success_response, make_error_response
from middleware.auth_middleware import jwt_required

# --- MODIFIED IMPORT ---
from app_extensions.user_configs_db_setup import user_configs_db_session_scope 
from models.user_config_models import UserTradingBot as UserTradingBotModel, UserApiCredential
from trading.bot_manager_service import BotManagerService 

logger = logging.getLogger("TradingBotBlueprint")

trading_bot_bp = Blueprint("trading_bot", __name__, url_prefix="/api/bots") # Renamed blueprint variable for consistency

@trading_bot_bp.route("", methods=["POST"])
@jwt_required
async def create_bot_config():
    user_id = g.user.get("id")
    if not user_id:
        return make_error_response("Authentication context error", code=500)

    log_prefix = f"CreateBotConfig (User:{user_id}):"
    try:
        data = await request.get_json()
        if not data:
            return make_error_response("Missing JSON payload", code=400)

        required_fields = ["bot_name", "credential_id", "strategy_name", "strategy_params_json", "market", "symbol", "timeframe"]
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return make_error_response(f"Missing required fields: {', '.join(missing_fields)}", code=400)

        if not (isinstance(data["bot_name"], str) and
                isinstance(data["credential_id"], int) and
                isinstance(data["strategy_name"], str) and
                isinstance(data["strategy_params_json"], dict) and
                isinstance(data["market"], str) and
                isinstance(data["symbol"], str) and
                isinstance(data["timeframe"], str)):
            return make_error_response("Invalid data types for one or more fields.", code=400)
        
        is_active = data.get("is_active", False)

        async with user_configs_db_session_scope() as session: # Async scope
            try:
                # Verify the credential_id belongs to the user and exists
                stmt_cred = select(UserApiCredential.credential_id).where(
                    UserApiCredential.user_id == user_id,
                    UserApiCredential.credential_id == data["credential_id"]
                )
                result_cred = await session.execute(stmt_cred)
                credential_exists = result_cred.scalar_one_or_none() # Returns the value or None
                if not credential_exists:
                    return make_error_response(f"API Credential ID {data['credential_id']} not found or does not belong to user.", code=404)

                new_bot_config = UserTradingBotModel(
                    user_id=user_id,
                    bot_name=data["bot_name"],
                    credential_id=data["credential_id"],
                    strategy_name=data["strategy_name"],
                    strategy_params_json=data["strategy_params_json"],
                    market=data["market"],
                    symbol=data["symbol"],
                    timeframe=data["timeframe"],
                    is_active=bool(is_active),
                    status_message="Configuration created." 
                )
                session.add(new_bot_config)
                await session.flush() # To get new_bot_config.bot_id
                
                logger.info(f"{log_prefix} Created bot configuration '{new_bot_config.bot_name}' (ID: {new_bot_config.bot_id}).")
                
                return make_success_response({
                    "message": "Bot configuration created successfully.",
                    "bot_id": new_bot_config.bot_id,
                    "bot_name": new_bot_config.bot_name,
                    "strategy_name": new_bot_config.strategy_name,
                    "symbol": new_bot_config.symbol,
                    "timeframe": new_bot_config.timeframe,
                    "is_active": new_bot_config.is_active,
                    "status_message": new_bot_config.status_message
                }, code=201)
            except IntegrityError as e:
                logger.warning(f"{log_prefix} Integrity error creating bot config. Detail: {e.orig}")
                return make_error_response("Bot configuration could not be saved due to a conflict (e.g., duplicate name).", code=409)
            except Exception as e_db:
                logger.error(f"{log_prefix} Database error creating bot config: {e_db}", exc_info=True)
                return make_error_response("Could not save bot configuration.", code=500)
    except Exception as e_outer:
        logger.error(f"{log_prefix} Unexpected error: {e_outer}", exc_info=True)
        return make_error_response("An unexpected error occurred.", code=500)

@trading_bot_bp.route("", methods=["GET"])
@jwt_required
async def list_user_bots():
    user_id = g.user.get("id")
    bot_manager: Optional[BotManagerService] = getattr(current_app, 'bot_manager_service', None)
    if not bot_manager:
        return make_error_response("Bot management service unavailable.", code=503)

    log_prefix = f"ListUserBots (User:{user_id}):"
    results = []
    try:
        async with user_configs_db_session_scope() as session: # Async scope
            stmt = select(UserTradingBotModel).where(UserTradingBotModel.user_id == user_id)
            result_db = await session.execute(stmt)
            bot_configs_db = result_db.scalars().all()
        
        # Fetch runtime status for each bot from BotManagerService (outside DB session)
        for bot_config_db in bot_configs_db:
            status_summary = await bot_manager.get_bot_status_summary(bot_config_db.bot_id)
            if status_summary:
                results.append(status_summary)
            else: 
                results.append({
                    "bot_id": bot_config_db.bot_id,
                    "bot_name": bot_config_db.bot_name,
                    "symbol": bot_config_db.symbol,
                    "timeframe": bot_config_db.timeframe,
                    "is_running": bot_config_db.is_active, 
                    "status_message": bot_config_db.status_message or ("Inactive" if not bot_config_db.is_active else "Unknown"),
                    "strategy": {"strategy_key": bot_config_db.strategy_name, "current_parameters": bot_config_db.strategy_params_json }
                })
        logger.info(f"{log_prefix} Retrieved {len(results)} bot configurations.")
        return make_success_response(results)
    except Exception as e:
        logger.error(f"{log_prefix} Error listing bot configurations: {e}", exc_info=True)
        return make_error_response("Could not retrieve bot configurations.", code=500)

@trading_bot_bp.route("/<int:bot_id>", methods=["GET"])
@jwt_required
async def get_bot_details(bot_id: int):
    user_id = g.user.get("id")
    bot_manager: Optional[BotManagerService] = getattr(current_app, 'bot_manager_service', None)
    if not bot_manager:
        return make_error_response("Bot management service unavailable.", code=503)

    log_prefix = f"GetBotDetails (User:{user_id}, BotID:{bot_id}):"
    try:
        async with user_configs_db_session_scope() as session: # Async scope
            stmt = select(UserTradingBotModel).where(
                UserTradingBotModel.bot_id == bot_id, 
                UserTradingBotModel.user_id == user_id
            )
            result_db = await session.execute(stmt)
            bot_config_db = result_db.scalars().first()
        
        if not bot_config_db:
            return make_error_response(f"Bot ID {bot_id} not found or not owned by user.", code=404)
        
        status_summary = await bot_manager.get_bot_status_summary(bot_id)
        if status_summary:
            return make_success_response(status_summary)
        else: 
            # Fallback if manager doesn't have it, but DB record exists (inactive bot)
            return make_success_response({
                "bot_id": bot_config_db.bot_id, "bot_name": bot_config_db.bot_name,
                "symbol": bot_config_db.symbol, "timeframe": bot_config_db.timeframe,
                "is_running": False, "status_message": bot_config_db.status_message or "Inactive",
                "strategy": {"strategy_key": bot_config_db.strategy_name, "current_parameters": bot_config_db.strategy_params_json }
            })
    except Exception as e:
        logger.error(f"{log_prefix} Error getting bot details: {e}", exc_info=True)
        return make_error_response(f"Could not retrieve status for bot ID {bot_id}.", code=500)


@trading_bot_bp.route("/<int:bot_id>/start", methods=["POST"])
@jwt_required
async def start_bot(bot_id: int):
    user_id = g.user.get("id")
    bot_manager: Optional[BotManagerService] = getattr(current_app, 'bot_manager_service', None)
    if not bot_manager:
        return make_error_response("Bot management service unavailable.", code=503)

    log_prefix = f"StartBot (User:{user_id}, BotID:{bot_id}):"
    try:
        async with user_configs_db_session_scope() as session: # Async scope for ownership check
            stmt = select(UserTradingBotModel.bot_id).where(
                UserTradingBotModel.bot_id == bot_id, 
                UserTradingBotModel.user_id == user_id
            )
            result_db = await session.execute(stmt)
            bot_config_exists = result_db.scalar_one_or_none()
        
        if not bot_config_exists:
            return make_error_response(f"Bot ID {bot_id} not found or not authorized.", code=404)
            
        success = await bot_manager.manage_bot_instance(bot_id, "start")
        if success:
            return make_success_response({"message": f"Bot ID {bot_id} start initiated."})
        else:
            return make_error_response(f"Failed to start bot ID {bot_id}. Check server logs.", code=500)
    except Exception as e:
        logger.error(f"{log_prefix} Error starting bot: {e}", exc_info=True)
        return make_error_response("Error initiating bot start.", code=500)


@trading_bot_bp.route("/<int:bot_id>/stop", methods=["POST"])
@jwt_required
async def stop_bot(bot_id: int):
    user_id = g.user.get("id")
    bot_manager: Optional[BotManagerService] = getattr(current_app, 'bot_manager_service', None)
    if not bot_manager:
        return make_error_response("Bot management service unavailable.", code=503)

    log_prefix = f"StopBot (User:{user_id}, BotID:{bot_id}):"
    try:
        async with user_configs_db_session_scope() as session: # Async scope for ownership check
            stmt = select(UserTradingBotModel.bot_id).where(
                UserTradingBotModel.bot_id == bot_id, 
                UserTradingBotModel.user_id == user_id
            )
            result_db = await session.execute(stmt)
            bot_config_exists = result_db.scalar_one_or_none()
            
        if not bot_config_exists:
            return make_error_response(f"Bot ID {bot_id} not found or not authorized.", code=404)

        success = await bot_manager.manage_bot_instance(bot_id, "stop")
        if success:
            return make_success_response({"message": f"Bot ID {bot_id} stop initiated."})
        else:
            return make_error_response(f"Failed to stop bot ID {bot_id}.", code=500)
    except Exception as e:
        logger.error(f"{log_prefix} Error stopping bot: {e}", exc_info=True)
        return make_error_response("Error initiating bot stop.", code=500)


@trading_bot_bp.route("/<int:bot_id>", methods=["PUT"])
@jwt_required
async def update_bot_config(bot_id: int):
    user_id = g.user.get("id")
    log_prefix = f"UpdateBotConfig (User:{user_id}, BotID:{bot_id}):"
    try:
        data = await request.get_json()
        if not data:
            return make_error_response("Missing JSON payload", code=400)

        async with user_configs_db_session_scope() as session: # Async scope
            try:
                stmt_bot = select(UserTradingBotModel).where(
                    UserTradingBotModel.bot_id == bot_id, 
                    UserTradingBotModel.user_id == user_id
                )
                result_bot = await session.execute(stmt_bot)
                bot_config = result_bot.scalars().first()

                if not bot_config:
                    return make_error_response("Bot configuration not found or not authorized.", code=404)

                # Fields that can be updated
                if "bot_name" in data: bot_config.bot_name = data["bot_name"]
                if "credential_id" in data:
                    new_cred_id = data["credential_id"]
                    if not isinstance(new_cred_id, int):
                         return make_error_response("credential_id must be an integer.", code=400)
                    stmt_cred = select(UserApiCredential.credential_id).where(
                        UserApiCredential.user_id == user_id, 
                        UserApiCredential.credential_id == new_cred_id
                    )
                    result_cred = await session.execute(stmt_cred)
                    cred_exists = result_cred.scalar_one_or_none()
                    if not cred_exists:
                        return make_error_response(f"New API Credential ID {new_cred_id} not found or does not belong to user.", code=400)
                    bot_config.credential_id = new_cred_id
                
                if "strategy_name" in data: bot_config.strategy_name = data["strategy_name"]
                if "strategy_params_json" in data: 
                    if not isinstance(data["strategy_params_json"], dict):
                        return make_error_response("strategy_params_json must be a JSON object.", code=400)
                    bot_config.strategy_params_json = data["strategy_params_json"]
                if "market" in data: bot_config.market = data["market"]
                if "symbol" in data: bot_config.symbol = data["symbol"]
                if "timeframe" in data: bot_config.timeframe = data["timeframe"]
                if "is_active" in data: 
                    logger.info(f"{log_prefix} 'is_active' field updated to {data['is_active']}. Manual start/stop may be required by BotManager.")
                    bot_config.is_active = bool(data["is_active"])
                
                # Commit handled by session_scope
                logger.info(f"{log_prefix} Updated bot configuration.")
                
                updated_data = {
                    "bot_id": bot_config.bot_id, "bot_name": bot_config.bot_name,
                    "strategy_name": bot_config.strategy_name, "symbol": bot_config.symbol,
                    "timeframe": bot_config.timeframe, "is_active": bot_config.is_active,
                    "status_message": bot_config.status_message
                }
                return make_success_response({"message": "Bot configuration updated.", "bot": updated_data})
            except IntegrityError as e:
                logger.warning(f"{log_prefix} Integrity error updating bot config. Detail: {e.orig}")
                return make_error_response("Update failed due to a conflict (e.g., duplicate name).", code=409)
            except Exception as e_db:
                logger.error(f"{log_prefix} Database error updating bot config: {e_db}", exc_info=True)
                return make_error_response("Could not update bot configuration.", code=500)
    except Exception as e_outer:
        logger.error(f"{log_prefix} Unexpected error: {e_outer}", exc_info=True)
        return make_error_response("An unexpected error occurred.", code=500)


@trading_bot_bp.route("/<int:bot_id>", methods=["DELETE"])
@jwt_required
async def delete_bot_config(bot_id: int): # Corrected path variable name
    user_id = g.user.get("id")
    bot_manager: Optional[BotManagerService] = getattr(current_app, 'bot_manager_service', None)
    if not bot_manager:
        return make_error_response("Bot management service unavailable.", code=503)

    log_prefix = f"DeleteBotConfig (User:{user_id}, BotID:{bot_id}):"
    try:
        async with user_configs_db_session_scope() as session: # Async scope
            stmt_select = select(UserTradingBotModel).where(
                UserTradingBotModel.bot_id == bot_id, 
                UserTradingBotModel.user_id == user_id
            )
            result_select = await session.execute(stmt_select)
            bot_config = result_select.scalars().first()

            if not bot_config:
                return make_error_response("Bot configuration not found or not authorized.", code=404)

            # Attempt to stop the bot if it's running
            # Check active_bots dictionary (thread-safe access if BotManagerService's lock is used internally)
            # This part needs to be careful about async access to bot_manager.active_bots
            # For simplicity, let's assume manage_bot_instance handles if bot is not active.
            if bot_config.bot_id in bot_manager.active_bots: # Direct check (might need lock in BotManagerService)
                 logger.info(f"{log_prefix} Bot is active, attempting to stop before deletion.")
                 await bot_manager.manage_bot_instance(bot_id, "stop")
                 await asyncio.sleep(0.5) 

            await session.delete(bot_config) # Async delete
            # Commit handled by session_scope
            logger.info(f"{log_prefix} Deleted bot configuration.")
            return make_success_response({"message": "Bot configuration deleted successfully."})
    except Exception as e:
        # Rollback handled by session_scope
        logger.error(f"{log_prefix} Error deleting bot config: {e}", exc_info=True)
        return make_error_response("Could not delete bot configuration.", code=500)