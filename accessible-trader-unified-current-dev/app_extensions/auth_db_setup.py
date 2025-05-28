# app_extensions/auth_db_setup.py

import logging
from quart import Quart
from sqlalchemy import text # Keep for raw SQL execution if needed
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession # Key async imports
from sqlalchemy.orm import declarative_base # Changed from sqlalchemy.ext.declarative
from contextlib import asynccontextmanager # For async context manager
from typing import Optional, AsyncGenerator # For type hinting

logger = logging.getLogger("AuthDbSetup")

# AuthUserBase remains the same, using declarative_base for model definitions
AuthUserBase = declarative_base()

# Module-level variables for the async engine and session factory
auth_db_async_engine = None
AsyncAuthSessionLocal: Optional[async_sessionmaker[AsyncSession]] = None

async def init_auth_db(app: Quart):
    """
    Initializes the asynchronous SQLAlchemy engine and session factory for the Auth Database (userdb).
    Stores them in the application extensions.

    Args:
        app (Quart): The Quart application instance.

    Raises:
        RuntimeError: If the database URL is not configured or connection fails.
    """
    global auth_db_async_engine, AsyncAuthSessionLocal
    
    db_url = app.config.get("AUTH_DB_CONNECTION_STRING")
    if not db_url:
        logger.critical("AUTH_DB_CONNECTION_STRING is not configured. Cannot initialize Auth Database.")
        raise RuntimeError("AUTH_DB_CONNECTION_STRING is required for user authentication.")

    # Ensure the URL is compatible with asyncmy (e.g., mysql+asyncmy://...)
    if not db_url.startswith("mysql+asyncmy://"):
        logger.warning(
            f"Auth DB URL '{db_url}' does not start with 'mysql+asyncmy://'. "
            "Ensure it's correctly formatted for the asyncmy driver."
        )
        # You might want to adapt the URL here if it's consistently missing the prefix
        # or raise an error if strict formatting is expected.

    try:
        auth_db_async_engine = create_async_engine(
            db_url,
            echo=app.config.get("SQLALCHEMY_ECHO_AUTH_DB", False), # Optional: echo SQL for debugging
            pool_recycle=app.config.get("SQLALCHEMY_POOL_RECYCLE_AUTH", 3600),
            # Add other engine options as needed, e.g., pool_size, max_overflow
        )

        AsyncAuthSessionLocal = async_sessionmaker(
            bind=auth_db_async_engine,
            class_=AsyncSession, # Use AsyncSession
            autocommit=False,
            autoflush=False,
            expire_on_commit=False # Often recommended for async sessions
        )

        app.extensions["auth_db_async_engine"] = auth_db_async_engine
        app.extensions["auth_db_session_factory"] = AsyncAuthSessionLocal
        
        logger.info(f"SQLAlchemy Async Auth Database (userdb) engine created for: {db_url.split('@')[-1]}")

        # Test connection using the new async session
        async with AsyncAuthSessionLocal() as session: # Create a session from the factory
            async with session.begin(): # Start a transaction (optional for SELECT 1, but good practice)
                await session.execute(text("SELECT 1"))
        logger.info("Async Auth Database (userdb) connection test successful.")

    except Exception as e:
        logger.critical(f"Failed to initialize SQLAlchemy Async Auth Database (userdb): {e}", exc_info=True)
        if auth_db_async_engine:
            await auth_db_async_engine.dispose() # Clean up engine if partially initialized
        raise RuntimeError(f"SQLAlchemy Async Auth Database (userdb) initialization failed: {e}") from e

async def close_auth_db(app: Quart):
    """
    Disposes of the asynchronous SQLAlchemy engine for the Auth Database during application shutdown.

    Args:
        app (Quart): The Quart application instance.
    """
    global auth_db_async_engine
    engine = app.extensions.pop("auth_db_async_engine", None) # Retrieve and remove from extensions
    if engine:
        try:
            await engine.dispose()
            logger.info("SQLAlchemy Async Auth Database (userdb) engine disposed successfully.")
        except Exception as e:
            logger.error(f"Error disposing SQLAlchemy Async Auth Database (userdb) engine: {e}", exc_info=True)
    else:
        logger.info("SQLAlchemy Async Auth Database (userdb) engine was not initialized or already disposed.")
    
    # Clear the global variable as well
    auth_db_async_engine = None
    app.extensions.pop("auth_db_session_factory", None) # Also remove factory from extensions


@asynccontextmanager
async def auth_db_session_scope() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide an asynchronous transactional scope around a series of Auth DB operations.
    This handles session creation, commit, rollback, and closing.

    Yields:
        AsyncSession: The active asynchronous SQLAlchemy session.

    Raises:
        RuntimeError: If the session factory (AsyncAuthSessionLocal) is not initialized.
    """
    if AsyncAuthSessionLocal is None:
        logger.critical("Auth DB Async Session Scope: AsyncAuthSessionLocal is None! DB not initialized properly.")
        raise RuntimeError("Auth Database (userdb) async session factory not initialized for scope.")

    session: AsyncSession = AsyncAuthSessionLocal()
    logger.debug("Auth DB Async Session Scope: Acquired session.")
    try:
        async with session.begin(): # Handles transaction begin and commit/rollback automatically
            yield session
            # If the block completes without error, session.begin() will commit.
        logger.debug("Auth DB Async Session Scope: Transaction committed (or no changes made).")
    except Exception as e:
        logger.error(
            f"Auth DB Async Session Scope: Exception occurred, transaction will be rolled back by session.begin(). Error: {type(e).__name__} - {e}",
            exc_info=True
        )
        # session.begin() handles rollback on exception.
        raise
    finally:
        try:
            await session.close()
            logger.debug("Auth DB Async Session Scope: Session closed.")
        except Exception as e_close:
            logger.error(f"Auth DB Async Session Scope: Error closing session: {e_close}", exc_info=True)