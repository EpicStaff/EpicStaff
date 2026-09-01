"""OpenAIEmbedder silently ignored base_url -- it had no constructor parameter for
it at all, so any local/self-hosted OpenAI-compatible endpoint configured for an
`openai`-provider row was never reached; requests always went to api.openai.com.
"""

from unittest.mock import patch

from embedder.openai import OpenAIEmbedder


def test_base_url_is_forwarded_to_the_openai_client():
    with patch("embedder.openai.OpenAI") as mock_openai:
        OpenAIEmbedder(
            api_key="sk-test",
            model_name="text-embedding-3-small",
            base_url="http://localhost:11434/v1",
        )

    mock_openai.assert_called_once_with(
        api_key="sk-test", base_url="http://localhost:11434/v1"
    )


def test_no_base_url_defaults_to_none_and_stays_backward_compatible():
    """Every existing caller that doesn't pass base_url must keep working --
    the OpenAI SDK treats base_url=None as its own default (api.openai.com)."""
    with patch("embedder.openai.OpenAI") as mock_openai:
        OpenAIEmbedder(api_key="sk-test", model_name="text-embedding-3-small")

    mock_openai.assert_called_once_with(api_key="sk-test", base_url=None)
