import pytest

pytest.importorskip(
    "psycopg",
    reason="requires libpq; only available in the Linux/Docker image, not this Windows venv",
    exc_type=ImportError,  # psycopg is installed but fails at import time without libpq
)

from domain.enums import EmbedderProviderEnum  # noqa: E402
from infrastructure.database.mappers.naive import embedding_row_to_embedding_config  # noqa: E402


def test_model_base_url_is_carried_into_the_embedding_config():
    config = embedding_row_to_embedding_config(
        "OpenAI", "text-embedding-3-small", "http://gateway:8080/v1"
    )

    assert config.provider == EmbedderProviderEnum.OPENAI
    assert config.base_url == "http://gateway:8080/v1"


def test_blank_model_base_url_maps_to_none_so_the_env_fallback_applies():
    config = embedding_row_to_embedding_config("OpenAI", "text-embedding-3-small", "")

    assert config.base_url is None


def test_headers_never_come_from_the_database_row():
    config = embedding_row_to_embedding_config("OpenAI", "text-embedding-3-small", None)

    assert config.extra_headers == {}
