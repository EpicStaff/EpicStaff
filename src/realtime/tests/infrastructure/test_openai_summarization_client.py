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
@pytest.mark.parametrize(
    ("base_url", "sdk_base_url"),
    # No override passes None, so the SDK keeps applying its own current default.
    [(None, None), ("https://my-proxy.internal/", "https://my-proxy.internal/v1")],
    ids=["sdk-default", "org-proxy"],
)
@patch("infrastructure.summarization.openai_summarization_client.AsyncOpenAI")
async def test_summaries_go_to_the_orgs_openai_endpoint(MockAsyncOpenAI, base_url, sdk_base_url):
    MockAsyncOpenAI.return_value.chat.completions.create = AsyncMock(return_value=_mock_openai_response())

    await OpenaiSummarizationClient(api_key="test_key", base_url=base_url).summarize_buffer("hello world")

    MockAsyncOpenAI.assert_called_once_with(api_key="test_key", base_url=sdk_base_url)
