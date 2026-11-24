import pytest

pytest.importorskip(
    "psycopg",
    reason="requires libpq; only available in the Linux/Docker image, not this Windows venv",
    exc_type=ImportError,  # psycopg is installed but fails at import time without libpq
)

from domain.enums import EmbedderProviderEnum  # noqa: E402
from infrastructure.database.mappers.embedding_arguments import embedding_call_arguments  # noqa: E402
from infrastructure.database.mappers.naive import embedding_row_to_embedding_config  # noqa: E402


def test_unset_settings_are_not_sent():
    assert embedding_call_arguments({"dimensions": 768, "encoding_format": None}) == {
        "dimensions": 768
    }


def test_a_gemini_task_type_reaches_gemini_as_its_uppercase_enum_value():
    from litellm.llms.vertex_ai.gemini_embeddings.batch_embed_content_transformation import (
        transform_openai_input_gemini_content,
    )
    from litellm.utils import get_optional_params_embeddings

    arguments = embedding_call_arguments({"task_type": "retrieval_document", "dimensions": 1536})
    # The request body LiteLLM builds for Gemini's batchEmbedContents from these arguments.
    optional_params = get_optional_params_embeddings(
        model="gemini-embedding-001", custom_llm_provider="gemini", **arguments
    )
    body = transform_openai_input_gemini_content(["text"], "gemini-embedding-001", optional_params)

    assert body["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert body["requests"][0]["outputDimensionality"] == 1536


def test_settings_connection_and_headers_never_come_from_the_database_row():
    config = embedding_row_to_embedding_config("OpenAI", "text-embedding-3-small")

    assert config.provider == EmbedderProviderEnum.OPENAI
    assert config.parameters == {}
    assert config.connection == {}
    assert config.extra_headers == {}
