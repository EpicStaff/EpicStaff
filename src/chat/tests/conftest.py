import os
from pathlib import Path

# Settings are read at import time by main.py; give tests a complete environment first.
os.environ.setdefault("RUN_IN_DOCKER", "1")
for name, value in {
    "CHAT_PORT": "8200",
    "CHAT_LOG_LEVEL": "INFO",
    "CHAT_DB_HOST": "chatdb",
    "CHAT_DB_PORT": "5432",
    "CHAT_DB_NAME": "chat",
    "CHAT_DB_USER": "chat",
    "CHAT_DB_PASSWORD": "chat",
    "REDIS_HOST": "redis",
    "REDIS_PORT": "6379",
    "REDIS_USER": "none",
    "REDIS_PASSWORD": "none",
    "CHAT_REDIS_DB": "2",
    "CHAT_TRUSTED_PROXIES": "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
    "CHAT_DJANGO_URL": "http://django_app:8000",
    "CHAT_DJANGO_HOST_HEADER": "localhost",
    "DJANGO_API_KEY": "system-key-for-tests-0123456789ab",
    "CHAT_PUBLIC_BASE_URL": "http://localhost",
    "CHAT_WIDGET_URL": "https://cdn.example.test/epicchat/embed.js",
    "CHAT_CALLBACK_URL": "http://chat:8200/chat/internal/v1/session-callbacks",
    "CHAT_DJANGO_TIMEOUT": "10s",
    "CHAT_IP_MESSAGE_RATE": "30/m",
    "CHAT_IP_CONVERSATION_RATE": "20/h",
    "CHAT_RECONCILE_INTERVAL": "0",
    "CHAT_STALE_RUN_AFTER": "5m",
    "CHAT_UNCONFIRMED_START_RELEASE": "1m",
    "CHAT_RUN_TIMEOUT": "30m",
    "CHAT_EVENT_RETENTION": "7d",
    "CHAT_CALLBACK_MAX_SKEW": "5m",
    "CHAT_IDENTITY_CACHE_TTL": "1m",
    "CHAT_TICKET_TTL": "1m",
    "CHAT_VISITOR_TOKEN_IDLE_TTL": "30d",
    "CHAT_STREAM_PING_INTERVAL": "1s",
    "CHAT_STREAM_MAX_LIFETIME": "5s",
    "CHAT_CONVERSATION_TOKEN_BUDGET_DEFAULT": "200000",
    "CHAT_CONVERSATION_TOKEN_BUDGET_MAX": "1000000",
    "CHAT_DAILY_TOKEN_BUDGET_DEFAULT": "1000000",
    "CHAT_DAILY_TOKEN_BUDGET_MAX": "50000000",
    "CHAT_RESPONSE_TIME_DEFAULT": "10m",
    "CHAT_RESPONSE_TIME_MAX": "1d",
    "CHAT_CLOSE_AFTER_DEFAULT": "24h",
    "CHAT_CLOSE_AFTER_MAX": "30d",
    "CHAT_ACTION_MAX_BYTES": "262144",
    "CHAT_EXTRA_DATA_MAX_BYTES": "8192",
}.items():
    os.environ.setdefault(name, value)

import fakeredis.aioredis
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from infrastructure.database.config import make_engine, make_session_factory
from infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from litestar.testing import AsyncTestClient
from sqlalchemy import text

from main import create_app
from settings import Settings, load_settings
from tests.fake_django import FakeDjango

SERVICE_ROOT = Path(__file__).resolve().parents[1]
TABLES = ("visitor_token", "callback_receipt", "daily_usage", "conversation_event", "message", "conversation", "visitor_number_counter", "operator_profile", "operator_alias", "binding")


@pytest.fixture(scope="session")
def settings() -> Settings:
    # A database of its own: the session_factory TRUNCATE must never reach a developer's chat data.
    base = load_settings()
    return base.model_copy(update={"CHAT_DB_NAME": base.CHAT_DB_NAME + "_test"})


@pytest.fixture(scope="session", autouse=True)
def migrated_database(settings):
    """Create the test database once and bring it to `alembic head` (sync: alembic runs its own loop)."""
    admin_url = f"postgresql://{settings.CHAT_DB_USER}:{settings.CHAT_DB_PASSWORD}@{settings.CHAT_DB_HOST}:{settings.CHAT_DB_PORT}/postgres"
    with psycopg.connect(admin_url, autocommit=True) as connection:
        exists = connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.CHAT_DB_NAME,)).fetchone()
        if not exists:
            connection.execute(f'CREATE DATABASE "{settings.CHAT_DB_NAME}"')
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


@pytest.fixture
async def session_factory(settings):
    engine = make_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    yield make_session_factory(engine)
    await engine.dispose()


@pytest.fixture
def uow_factory(session_factory):
    return lambda: SQLAlchemyUnitOfWork(session_factory)


@pytest.fixture
def django():
    return FakeDjango()


@pytest.fixture
async def redis_client():
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture
async def client(settings, session_factory, django, redis_client):
    app = create_app(settings, django_transport=django.transport, redis_client=redis_client)
    async with AsyncTestClient(app=app) as test_client:
        yield test_client
