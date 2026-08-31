"""base_url exists on the EmbeddingModel row but was dropped by this query's shape.

EmbeddingModel.base_url is mapped on both the Django model and this SQLAlchemy
model, so a local/self-hosted embedding endpoint could be configured -- but
get_embedder_configuration's returned dict never selected the column, so every
consumer (_set_embedder_config) received a config with no base_url at all.
"""

from unittest.mock import MagicMock

from storage.base_storage import BaseORMStorage
from models.orm import NaiveRag, EmbeddingModel


def _make_session(*, rag_instance, model_instance):
    session = MagicMock()

    def query_side_effect(entity):
        chain = MagicMock()
        if entity is NaiveRag:
            chain.options.return_value.filter.return_value.one_or_none.return_value = (
                rag_instance
            )
        elif entity is EmbeddingModel:
            chain.options.return_value.filter.return_value.one_or_none.return_value = (
                model_instance
            )
        else:
            raise AssertionError(f"Unexpected query target: {entity}")
        return chain

    session.query.side_effect = query_side_effect
    return session


def test_get_embedder_configuration_returns_base_url():
    embedder = MagicMock(model_id=5, api_key_secret_id=None)
    rag_instance = MagicMock(embedder=embedder)

    provider = MagicMock()
    provider.name = "openai"

    model_instance = MagicMock(embedding_provider=provider, base_url="http://localhost:11434/v1")
    model_instance.name = "text-embedding-3-small"

    session = _make_session(rag_instance=rag_instance, model_instance=model_instance)
    storage = BaseORMStorage(session=session)

    config = storage.get_embedder_configuration(rag_id=1, rag_type="naive")

    assert config["base_url"] == "http://localhost:11434/v1"
    assert config["model_name"] == "text-embedding-3-small"
    assert config["provider"] == "openai"


def test_get_embedder_configuration_returns_none_base_url_when_unset():
    """A cloud embedder row has no base_url -- the key must still be present as None,
    not omitted, so downstream `.get("base_url")` callers see an explicit absence."""
    embedder = MagicMock(model_id=5, api_key_secret_id=None)
    rag_instance = MagicMock(embedder=embedder)

    provider = MagicMock()
    provider.name = "openai"

    model_instance = MagicMock(embedding_provider=provider, base_url=None)
    model_instance.name = "text-embedding-3-small"

    session = _make_session(rag_instance=rag_instance, model_instance=model_instance)
    storage = BaseORMStorage(session=session)

    config = storage.get_embedder_configuration(rag_id=1, rag_type="naive")

    assert "base_url" in config
    assert config["base_url"] is None
