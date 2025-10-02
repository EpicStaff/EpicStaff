from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import os
import sys
from dotenv import load_dotenv, find_dotenv
from loguru import logger

if "--debug" in sys.argv:
    logger.info("RUNNING IN DEBUG MODE")
    load_dotenv(find_dotenv("debug.env"))
else:
    load_dotenv(find_dotenv(".env"))



def get_required_env_var(key: str) -> str:
    """
    If you see this error during local launch set all required variables in manager/.env
    """
    value = os.getenv(key)
    if value is None:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


DB_USER = get_required_env_var("DB_MANAGER_USER")
DB_PASSWORD = get_required_env_var("DB_MANAGER_PASSWORD")
DB_NAME = get_required_env_var("DB_NAME")
DB_PORT = get_required_env_var("DB_PORT")
DB_HOST_NAME = get_required_env_var("DB_HOST_NAME")

DATABASE_URL = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST_NAME}:{DB_PORT}/{DB_NAME}"
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True only for debugging
    pool_size=10,  # Number of connections to maintain in pool
    max_overflow=100,  # Additional connections beyond pool_size
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={
        "server_settings": {
            "application_name": "manager_service",
        }
    },
)

# Session factory
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=True,
    autocommit=False,
)
