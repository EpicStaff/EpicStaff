"""_set_embedder_config dropped base_url on every known-provider branch except
CustomEmbedder -- OpenAIEmbedder had no parameter to receive it, so a
local/self-hosted endpoint configured for provider="openai" was silently ignored
(EST-3696, break b, strategy half).

Also guards the outer-exception fallback: a construction failure used to be
swallowed and served by a default OpenAI embedder built from the container's
ambient OPENAI_API_KEY (the exact landmine credential_mapper.MissingCredentialError
was introduced to prevent one layer earlier). It must now raise loudly instead.
"""

from unittest.mock import patch

import pytest

from rag.naive_rag_strategy import EmbedderConfigurationError, NaiveRAGStrategy


def test_openai_provider_forwards_base_url():
    strategy = NaiveRAGStrategy()
    config = {
        "provider": "openai",
        "model_name": "text-embedding-3-small",
        "api_key": "sk-test",
        "base_url": "http://localhost:11434/v1",
    }

    with patch("rag.naive_rag_strategy.OpenAIEmbedder") as mock_embedder_class:
        mock_embedder_class.__name__ = "OpenAIEmbedder"
        strategy._set_embedder_config(config)

    mock_embedder_class.assert_called_once_with(
        api_key="sk-test",
        model_name="text-embedding-3-small",
        base_url="http://localhost:11434/v1",
    )


def test_openai_provider_with_no_base_url_still_works():
    """Backward compatible: an openai row with no base_url configured must not
    regress -- base_url=None is passed through and the SDK falls back to its own
    default."""
    strategy = NaiveRAGStrategy()
    config = {
        "provider": "openai",
        "model_name": "text-embedding-3-small",
        "api_key": "sk-test",
    }

    with patch("rag.naive_rag_strategy.OpenAIEmbedder") as mock_embedder_class:
        mock_embedder_class.__name__ = "OpenAIEmbedder"
        strategy._set_embedder_config(config)

    mock_embedder_class.assert_called_once_with(
        api_key="sk-test",
        model_name="text-embedding-3-small",
        base_url=None,
    )


def test_other_known_providers_do_not_receive_base_url():
    """Deliberately narrower-than-ticket scope: only OpenAIEmbedder gets base_url."""
    strategy = NaiveRAGStrategy()
    config = {
        "provider": "cohere",
        "model_name": "embed-v4.0",
        "api_key": "sk-test",
        "base_url": "http://localhost:11434/v1",
    }

    with patch("rag.naive_rag_strategy.CohereEmbedder") as mock_embedder_class:
        mock_embedder_class.__name__ = "CohereEmbedder"
        strategy._set_embedder_config(config)

    mock_embedder_class.assert_called_once_with(
        api_key="sk-test", model_name="embed-v4.0"
    )


def test_construction_failure_raises_instead_of_silently_falling_back():
    """The real defect: a missing 'provider' key used to be swallowed and served
    by a default OpenAI embedder built from the ambient environment key."""
    strategy = NaiveRAGStrategy()
    config = {"model_name": "text-embedding-3-small", "api_key": "sk-test"}

    with pytest.raises(EmbedderConfigurationError):
        strategy._set_embedder_config(config)


def test_construction_failure_does_not_construct_a_default_openai_embedder():
    strategy = NaiveRAGStrategy()
    config = {"model_name": "text-embedding-3-small", "api_key": "sk-test"}

    with patch("rag.naive_rag_strategy.OpenAIEmbedder") as mock_embedder_class:
        with pytest.raises(EmbedderConfigurationError):
            strategy._set_embedder_config(config)

    mock_embedder_class.assert_not_called()


def test_no_default_embedding_function_left_behind():
    """_create_default_embedding_function is dead code now that the fallback
    is gone -- guard against it being reintroduced."""
    assert not hasattr(NaiveRAGStrategy, "_create_default_embedding_function")
