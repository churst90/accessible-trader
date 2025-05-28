# app_extensions/user_configs_db_setup.py

import logging
from quart import Quart
from sqlalchemy import text # Keep for raw SQL execution if needed
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession # Key async imports
from sqlalchemy.orm import declarative_base # Changed from sqlalchemy.ext.declarative
from contextlib import asynccontextmanager # For async context manager
from typing import Optional, AsyncGenerator # For type hinting

logger = logging.getLogger("UserConfigsDbSetup")

# UserConfigsBase remains the same for model definitions
UserConfigsBase = declarative_base()

# Module-level variables for the async engine and session factory
user_configs_async_engine = None
AsyncUserConfigsSessionLocal: Optional[async_sessionmaker[AsyncSession]] = None

async def init_user_configs_db(app: Quart):
    """
    Initializes the asynchronous SQLAlchemy engine and session factory for the User Configurations Database.
    Stores them in the application extensions.

    Args:
        app (Quart): The Quart application instance.

    Raises:
        RuntimeError: If the database URL is not configured or connection fails.
    """
    global user_configs_async_engine, AsyncUserConfigsSessionLocal
    
    db_url = app.config.get("USER_CONFIGS_DB_CONNECTION_STRING")
    if not db_url:
        logger.critical("USER_CONFIGS_DB_CONNECTION_STRING not set. Cannot initialize User Configs Database.")
        raise RuntimeError("USER_CONFIGS_DB_CONNECTION_STRING is required for user configurations.")

    # Ensure the URL is compatible with asyncmy (e.g., mysql+asyncmy://...)
    if not db_url.startswith("mysql+asyncmy://"):
        logger.warning(
            f"User Configs DB URL '{db_url}' does not start with 'mysql+asyncmy://'. "
            "Ensure it's correctly formatted for the asyncmy driver."
        )

    try:
        user_configs_async_engine = create_async_engine(
            db_url,
            echo=app.config.get("SQLALCHEMY_ECHO_USER_CONFIGS_DB", False), # Optional echo
            pool_recycle=app.config.get("SQLALCHEMY_POOL_RECYCLE_USER_CONFIGS", 3600),
            # Add other engine options as needed
        )

        AsyncUserConfigsSessionLocal = async_sessionmaker(
            bind=user_configs_async_engine,
            class_=AsyncSession,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False 
        )

        app.extensions["user_configs_async_engine"] = user_configs_async_engine
        app.extensions["user_configs_session_factory"] = AsyncUserConfigsSessionLocal
        
        logger.info(f"SQLAlchemy Async User Configs Database engine created for: {db_url.split('@')[-1]}")

        # Test connection
        async with AsyncUserConfigsSessionLocal() as session:
            async with session.begin():
                await session.execute(text("SELECT 1"))
        logger.info("Async User Configs Database connection test successful.")

    except Exception as e:
        logger.critical(f"Failed to initialize SQLAlchemy Async User Configs Database: {e}", exc_info=True)
        if user_configs_async_engine:
            await user_configs_async_engine.dispose()
        raise RuntimeError(f"SQLAlchemy Async User Configs Database initialization failed: {e}") from e

async def close_user_configs_db(app: Quart):
    """
    Disposes of the asynchronous SQLAlchemy engine for the User Configs Database during application shutdown.

    Args:
        app (Quart): The Quart application instance.
    """
    global user_configs_async_engine # Make sure to reference the global if modifying
    engine = app.extensions.pop("user_configs_async_engine", None)
    if engine:
        try:
            await engine.dispose()
            logger.info("SQLAlchemy Async User Configs Database engine disposed successfully.")
        except Exception as e:
            logger.error(f"Error disposing SQLAlchemy Async User Configs Database engine: {e}", exc_info=True)
    else:
        logger.info("SQLAlchemy Async User Configs Database engine was not initialized or already disposed.")
        
    user_configs_async_engine = None # Clear global reference
    app.extensions.pop("user_configs_session_factory", None)


@asynccontextmanager
async def user_configs_db_session_scope() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide an asynchronous transactional scope around a series of User Configs DB operations.
    This handles session creation, commit, rollback, and closing.

    Yields:
        AsyncSession: The active asynchronous SQLAlchemy session.

    Raises:
        RuntimeError: If the session factory (AsyncUserConfigsSessionLocal) is not initialized.
    """
    if AsyncUserConfigsSessionLocal is None:
        logger.critical("UserConfigs DB Async Session Scope: AsyncUserConfigsSessionLocal is None! DB not initialized properly.")
        raise RuntimeError("User Configs Database async session factory not initialized for scope.")

    session: AsyncSession = AsyncUserConfigsSessionLocal()
    logger.debug("UserConfigs DB Async Session Scope: Acquired session.")
    try:
        async with session.begin(): # Handles transaction begin and commit/rollback
            yield session
        logger.debug("UserConfigs DB Async Session Scope: Transaction committed (or no changes made).")
    except Exception as e:
        logger.error(
            f"UserConfigs DB Async Session Scope: Exception occurred, transaction will be rolled back by session.begin(). Error: {type(e).__name__} - {e}",
            exc_info=True
        )
        raise
    finally:
        try:
            await session.close()
            logger.debug("UserConfigs DB Async Session Scope: Session closed.")
        except Exception as e_close:
            logger.error(f"UserConfigs DB Async Session Scope: Error closing session: {e_close}", exc_info=True)