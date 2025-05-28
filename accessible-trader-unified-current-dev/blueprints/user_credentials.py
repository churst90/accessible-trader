# blueprints/user_credentials.py

import logging
from quart import Blueprint, request, g, current_app 
from sqlalchemy import select # Import select
from sqlalchemy.exc import IntegrityError

# App-specific imports
from utils.response import make_success_response, make_error_response
from middleware.auth_middleware import jwt_required

# Imports for DB (async scope) and Encryption
from app_extensions.user_configs_db_setup import user_configs_db_session_scope # Use async scope
from models.user_config_models import UserApiCredential
from services.encryption_service import encrypt_data 

logger = logging.getLogger("UserCredentialsBlueprint")

user_credentials_bp = Blueprint("user_credentials", __name__, url_prefix="/api/credentials")

@user_credentials_bp.route("", methods=["POST"])
@jwt_required
async def add_api_credential():
    """
    Adds a new API credential set for the authenticated user.
    Expects JSON payload with: service_name, credential_name, api_key,
                                api_secret (optional), aux_data (optional JSON string or dict),
                                is_testnet (optional boolean), notes (optional).
    """
    user_id = g.user.get("id")
    if not user_id:
        logger.error("add_api_credential: User ID not found in g.user after @jwt_required.")
        return make_error_response("Authentication context error", code=500)

    log_prefix = f"AddApiCredential (User:{user_id}):"
    try:
        data = await request.get_json()
        if not data:
            return make_error_response("Missing JSON payload", code=400)

        service_name = data.get("service_name")
        credential_name = data.get("credential_name")
        api_key_plain = data.get("api_key")
        api_secret_plain = data.get("api_secret") 
        aux_data_plain = data.get("aux_data")   
        is_testnet = data.get("is_testnet", False) 
        notes = data.get("notes")               

        if not all([service_name, credential_name, api_key_plain]):
            return make_error_response("Missing required fields: service_name, credential_name, api_key", code=400)

        # Encryption is CPU-bound, could be offloaded if it becomes a bottleneck.
        # For now, keeping it inline.
        encrypted_api_key = encrypt_data(api_key_plain)
        if not encrypted_api_key:
            logger.error(f"{log_prefix} Failed to encrypt API key for service {service_name}.")
            return make_error_response("Failed to secure API key", code=500)

        encrypted_api_secret = None
        if api_secret_plain:
            encrypted_api_secret = encrypt_data(api_secret_plain)
            if not encrypted_api_secret:
                logger.error(f"{log_prefix} Failed to encrypt API secret for service {service_name}.")
                return make_error_response("Failed to secure API secret", code=500)
        
        encrypted_aux_data_str = None
        if aux_data_plain:
            aux_data_to_encrypt = json.dumps(aux_data_plain) if isinstance(aux_data_plain, (dict, list)) else str(aux_data_plain)
            encrypted_aux_data_str = encrypt_data(aux_data_to_encrypt)
            if not encrypted_aux_data_str:
                logger.error(f"{log_prefix} Failed to encrypt auxiliary data for service {service_name}.")
                return make_error_response("Failed to secure auxiliary data", code=500)

        async with user_configs_db_session_scope() as session: # Use async session scope
            try:
                new_credential = UserApiCredential(
                    user_id=user_id,
                    service_name=service_name.lower(),
                    credential_name=credential_name,
                    encrypted_api_key=encrypted_api_key,
                    encrypted_api_secret=encrypted_api_secret,
                    encrypted_aux_data=encrypted_aux_data_str,
                    is_testnet=bool(is_testnet),
                    notes=notes
                )
                session.add(new_credential)
                # Commit is handled by user_configs_db_session_scope upon successful exit of 'async with session.begin():'
                # We might need to flush to get the ID if it's auto-generated and needed immediately.
                await session.flush() # To get new_credential.credential_id if auto-incremented
                
                logger.info(f"{log_prefix} Successfully added API credential '{credential_name}' for service '{service_name}'. ID: {new_credential.credential_id}")
                
                return make_success_response({
                    "message": "API credential added successfully.",
                    "credential_id": new_credential.credential_id,
                    "service_name": new_credential.service_name,
                    "credential_name": new_credential.credential_name,
                    "is_testnet": new_credential.is_testnet
                }, code=201)
            except IntegrityError as e:
                # Rollback is handled by session_scope
                logger.warning(f"{log_prefix} Integrity error adding credential for service '{service_name}', "f"name '{credential_name}'. Likely duplicate. Error: {e}. SQLAlchemy Detail: {e.orig if hasattr(e, 'orig') else 'N/A'}")
                return make_error_response("An API credential with this name already exists for this service. Please use a unique name.", code=409)
            except Exception as e_db: # Catch other DB errors
                # Rollback is handled by session_scope
                logger.error(f"{log_prefix} Database error adding API credential for {service_name}: {e_db}", exc_info=True)
                return make_error_response("Could not save API credential due to a server error.", code=500)

    except Exception as e_outer:
        logger.error(f"{log_prefix} Unexpected error in add_api_credential for service {data.get('service_name') if data else 'N/A'}: {e_outer}", exc_info=True)
        return make_error_response("An unexpected error occurred.", code=500)


@user_credentials_bp.route("", methods=["GET"])
@jwt_required
async def list_api_credentials():
    """
    Lists all API credentials (metadata only) for the authenticated user.
    """
    user_id = g.user.get("id")
    if not user_id:
        logger.error("list_api_credentials: User ID not found in g.user.")
        return make_error_response("Authentication context error", code=500)
    
    log_prefix = f"ListApiCredentials (User:{user_id}):"
    try:
        async with user_configs_db_session_scope() as session:
            stmt = (
                select(
                    UserApiCredential.credential_id,
                    UserApiCredential.service_name,
                    UserApiCredential.credential_name,
                    UserApiCredential.is_testnet,
                    UserApiCredential.notes,
                    UserApiCredential.created_at,
                    UserApiCredential.updated_at
                )
                .where(UserApiCredential.user_id == user_id)
                .order_by(UserApiCredential.service_name, UserApiCredential.credential_name)
            )
            result = await session.execute(stmt)
            credentials = result.all() # Fetches all rows as Row objects
        
        result_list = [
            {
                "credential_id": cred.credential_id,
                "service_name": cred.service_name,
                "credential_name": cred.credential_name,
                "is_testnet": cred.is_testnet,
                "notes": cred.notes,
                "created_at": cred.created_at.isoformat() if cred.created_at else None,
                "updated_at": cred.updated_at.isoformat() if cred.updated_at else None,
            }
            for cred in credentials
        ]
        logger.info(f"{log_prefix} Retrieved {len(result_list)} API credential(s).")
        return make_success_response(result_list)
        
    except Exception as e:
        logger.error(f"{log_prefix} Error listing API credentials: {e}", exc_info=True)
        return make_error_response("Could not retrieve API credentials.", code=500)

@user_credentials_bp.route("/<int:credential_id>", methods=["DELETE"])
@jwt_required
async def delete_api_credential(credential_id: int):
    """
    Deletes a specific API credential for the authenticated user.
    """
    user_id = g.user.get("id")
    if not user_id:
        logger.error(f"delete_api_credential: User ID not found in g.user for credential_id {credential_id}.")
        return make_error_response("Authentication context error", code=500)

    log_prefix = f"DeleteApiCredential (User:{user_id}, CredID:{credential_id}):"
    try:
        async with user_configs_db_session_scope() as session:
            # First, fetch the credential to ensure it exists and belongs to the user
            stmt_select = select(UserApiCredential).where(
                UserApiCredential.credential_id == credential_id,
                UserApiCredential.user_id == user_id
            )
            result = await session.execute(stmt_select)
            credential = result.scalars().first()

            if not credential:
                logger.warning(f"{log_prefix} Attempted to delete non-existent or unauthorized credential.")
                return make_error_response("API credential not found or not authorized to delete.", code=404)

            # If found and owned, delete it
            await session.delete(credential)
            # Commit handled by session_scope
            logger.info(f"{log_prefix} Successfully deleted API credential (Name: {credential.credential_name}, Service: {credential.service_name}).")
            return make_success_response({"message": "API credential deleted successfully."})

    except Exception as e:
        # Rollback handled by session_scope
        logger.error(f"{log_prefix} Error deleting API credential: {e}", exc_info=True)
        return make_error_response("Could not delete API credential.", code=500)

# TODO: Implement PUT /<int:credential_id> for updating credentials.
# This would involve fetching, verifying ownership, allowing changes to certain fields,
# re-encrypting sensitive fields if they are updated, and then committing.