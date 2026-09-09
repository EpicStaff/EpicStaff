from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.summarization.openai_summarization_client import (
    OpenaiSummarizationClient,
)


def _mock_openai_response(text: str = "summary"):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=text))]
    return response


@pytest.mark.asyncio
@patch("infrastructure.summarization.openai_summarization_client.AsyncOpenAI")
async def test_default_base_url_is_none_reproducing_sdk_default(MockAsyncOpenAI):
    """No override must not pass a constructed literal,
    letting AsyncOpenAI apply its own current default base_url."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_mock_openai_response())
    MockAsyncOpenAI.return_value = mock_client

    client = OpenaiSummarizationClient(api_key="test_key")
    await client.summarize_buffer("hello world")

    MockAsyncOpenAI.assert_called_once_with(api_key="test_key", base_url=None)


@pytest.mark.asyncio
@patch("infrastructure.summarization.openai_summarization_client.AsyncOpenAI")
async def test_custom_base_url_is_derived_and_passed(MockAsyncOpenAI):
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_mock_openai_response())
    MockAsyncOpenAI.return_value = mock_client

    client = OpenaiSummarizationClient(
        api_key="test_key", base_url="https://my-proxy.internal/"
    )
    await client.summarize_buffer("hello world")

    MockAsyncOpenAI.assert_called_once_with(
        api_key="test_key", base_url="https://my-proxy.internal/v1"
    )
