# services/encryption_service.py

import logging
import base64
import hashlib
from quart import current_app # To access the app's SECRET_KEY or a dedicated ENCRYPTION_KEY
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("EncryptionService")

# Global variable to store the Fernet instance, initialized once when first needed.
_fernet_instance: Fernet | None = None
_derived_encryption_key: bytes | None = None # Store the derived key for clarity

def _initialize_fernet():
    """
    Initializes the Fernet instance using a key derived from the application's
    configuration. This function is called internally on the first encryption
    or decryption attempt.

    It's recommended to use a dedicated, strong, randomly generated key for encryption,
    stored in your environment variables (e.g., ENCRYPTION_KEY_FERNET).
    As a fallback, this implementation can derive a key from the app's SECRET_KEY,
    but this is less ideal as SECRET_KEY might be used for other purposes and
    changing it would invalidate all encrypted data.

    Raises:
        ValueError: If a suitable encryption key cannot be obtained or Fernet fails to initialize.
    """
    global _fernet_instance, _derived_encryption_key
    if _fernet_instance is not None:
        return

    # Option 1 (Recommended for Production): Use a dedicated ENCRYPTION_KEY_FERNET from .env
    # This key should be a 32-byte URL-safe base64-encoded string.
    # You can generate one using: Fernet.generate_key().decode()
    dedicated_env_key_str = current_app.config.get("ENCRYPTION_KEY_FERNET")

    if dedicated_env_key_str:
        try:
            # Ensure the key is 32 bytes when decoded
            decoded_key = base64.urlsafe_b64decode(dedicated_env_key_str.encode('utf-8'))
            if len(decoded_key) == 32:
                _derived_encryption_key = dedicated_env_key_str.encode('utf-8')
                logger.info("EncryptionService: Using dedicated ENCRYPTION_KEY_FERNET.")
            else:
                logger.error("ENCRYPTION_KEY_FERNET from .env is not a valid 32-byte key when decoded. "
                             "Falling back to deriving from SECRET_KEY (less secure).")
                dedicated_env_key_str = None # Force fallback
        except Exception as e_decode:
            logger.error(f"Error decoding ENCRYPTION_KEY_FERNET: {e_decode}. "
                         "Falling back to deriving from SECRET_KEY (less secure).")
            dedicated_env_key_str = None # Force fallback
    
    if not _derived_encryption_key: # Fallback to deriving from SECRET_KEY
        app_secret_key_str = current_app.config.get("SECRET_KEY")
        if not app_secret_key_str:
            logger.critical("SECRET_KEY is not configured. Cannot initialize EncryptionService.")
            raise ValueError("A SECRET_KEY (or ideally ENCRYPTION_KEY_FERNET) must be set for encryption.")

        logger.warning("EncryptionService: Deriving encryption key from SECRET_KEY. "
                       "It is strongly recommended to set a dedicated ENCRYPTION_KEY_FERNET in your .env file.")
        
        # Use SHA256 to get a 32-byte hash from SECRET_KEY, then base64 encode it for Fernet.
        # This makes the encryption key deterministic based on SECRET_KEY.
        hashed_key_for_fernet = hashlib.sha256(app_secret_key_str.encode('utf-8')).digest() # 32 raw bytes
        _derived_encryption_key = base64.urlsafe_b64encode(hashed_key_for_fernet) # URL-safe base64 encoded key

    try:
        _fernet_instance = Fernet(_derived_encryption_key)
        logger.info("EncryptionService initialized successfully with Fernet.")
    except Exception as e_fernet:
        logger.critical(f"Failed to initialize Fernet for EncryptionService using key (derived or dedicated): {e_fernet}", exc_info=True)
        _fernet_instance = None # Ensure it's None on failure
        _derived_encryption_key = None
        raise ValueError(f"Fernet instance creation error: {e_fernet}")


def encrypt_data(plain_text: str) -> str | None:
    """
    Encrypts a given string using the initialized Fernet instance.

    Args:
        plain_text (str): The text to be encrypted. It will be UTF-8 encoded.

    Returns:
        str | None: The encrypted text (as a UTF-8 decoded string of the Fernet token),
                    or None if encryption fails or the service is not initialized.
    """
    if _fernet_instance is None:
        try:
            _initialize_fernet()
        except ValueError: # Raised if key config is missing
            logger.error("EncryptionService could not be initialized. Cannot encrypt data.")
            return None
        if _fernet_instance is None: # Still None after attempted init (should not happen if ValueError not caught)
            logger.error("EncryptionService not initialized after attempt. Cannot encrypt data.")
            return None
    
    if not isinstance(plain_text, str):
        logger.warning(f"Encrypt_data: input was not a string (type: {type(plain_text)}), attempting to convert.")
        try:
            plain_text = str(plain_text)
        except Exception:
            logger.error(f"Encrypt_data: Could not convert input of type {type(plain_text)} to string.")
            return None

    try:
        encrypted_bytes = _fernet_instance.encrypt(plain_text.encode('utf-8'))
        return encrypted_bytes.decode('utf-8') # Store the Fernet token as a string
    except Exception as e:
        logger.error(f"Error encrypting data: {e}", exc_info=True)
        return None


def decrypt_data(encrypted_text: str) -> str | None:
    """
    Decrypts a given string (which should be a Fernet token) using the initialized Fernet instance.

    Args:
        encrypted_text (str): The UTF-8 string representing the Fernet token to be decrypted.

    Returns:
        str | None: The decrypted string, or None if decryption fails
                    (e.g., invalid token, wrong key, data tampering, or service not initialized).
    """
    if _fernet_instance is None:
        try:
            _initialize_fernet()
        except ValueError:
            logger.error("EncryptionService could not be initialized. Cannot decrypt data.")
            return None
        if _fernet_instance is None:
            logger.error("EncryptionService not initialized after attempt. Cannot decrypt data.")
            return None

    if not encrypted_text: # Handle empty string case
        logger.debug("Decrypt_data: received empty or None encrypted_text.")
        return None # Or return "" if that's more appropriate for your logic
            
    if not isinstance(encrypted_text, str):
        logger.error(f"Decrypt_data: input was not a string (type: {type(encrypted_text)}). Cannot decrypt.")
        return None

    try:
        decrypted_bytes = _fernet_instance.decrypt(encrypted_text.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except InvalidToken:
        # This is a specific Fernet exception for when the token is invalid,
        # which can mean it's corrupted, not a valid Fernet token, or encrypted with a different key.
        logger.error("Error decrypting data: Invalid token or key. This could be due to data tampering, "
                     "an incorrect encryption key (e.g., if SECRET_KEY changed and was used for derivation), "
                     "or the data not being a valid Fernet token.")
        return None
    except Exception as e:
        # Catch other potential errors during decryption (e.g., unexpected type issues)
        logger.error(f"An unexpected error occurred during data decryption: {e}", exc_info=True)
        return None