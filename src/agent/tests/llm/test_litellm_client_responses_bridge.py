"""
LiteLLMClient through a real litellm Router against a local stub provider.

A reasoning model called with tools and reasoning_effort is sent by litellm through
its Responses API bridge, which imports litellm's MCP catalog regardless of
_skip_mcp_handler. That import needs mcp 2.x; with mcp 1.x every such call failed
with "cannot import name 'CacheableResult' from 'mcp.types'". No mock stands in for
litellm here, because the failure lives inside it.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from app.llm.litellm_client import LiteLLMClient
from app.llm.retry import RetryPolicy
from app.llm.router_pool import RouterPool
from app.loop.agent_loop import _build_model_config
from app.loop.context import AgentContext
from app.tools.registry import ToolSpec
from shared.models.agent_service import AgentSpec
from shared.models.ai_providers import LLMConfigData, LLMData

from tests.cancellation import never_cancelled

_RESPONSES_API_REPLY = {
    "id": "resp_1",
    "object": "response",
    "created_at": 1,
    "status": "completed",
    "model": "gpt-6-luna",
    "output": [
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "hi", "annotations": []}],
        }
    ],
    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    "parallel_tool_calls": True,
    "tool_choice": "auto",
    "tools": [],
}

_SEARCH_TOOL = ToolSpec(
    name="search",
    description="Search the web.",
    parameters_schema={"type": "object", "properties": {}},
)


@pytest.fixture
def responses_api_stub():
    """Answer every POST with a completed Responses API reply; yield (base_url, paths)."""
    request_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("content-length", 0)))
            request_paths.append(self.path)
            body = json.dumps(_RESPONSES_API_REPLY).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", request_paths
    server.shutdown()
    server.server_close()
    thread.join()


def _model_config(provider: str, llm_config: LLMConfigData) -> dict:
    agent = AgentSpec(
        id=1, name="a", instructions="i", llm=LLMData(provider=provider, config=llm_config)
    )
    context = AgentContext(
        agent=agent, attachments=[], correlation_id="c", is_cancelled=never_cancelled
    )
    return _build_model_config(context)


@pytest.mark.parametrize(
    ("provider", "api_version"),
    [("openai", None), ("azure", "2025-04-01-preview")],
    ids=["openai", "azure"],
)
async def test_reasoning_model_with_tools_completes_through_the_responses_api(
    responses_api_stub, provider, api_version
):
    base_url, request_paths = responses_api_stub
    model_config = _model_config(
        provider,
        LLMConfigData(
            model="gpt-6-luna",
            api_key="sk-test",
            base_url=base_url,
            api_version=api_version,
            reasoning_effort="high",
        ),
    )
    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), pool=RouterPool())

    chunks = [
        chunk
        async for chunk in client.chat(
            [{"role": "user", "content": "hello"}], [_SEARCH_TOOL], model_config, stream=False
        )
    ]

    assert [chunk.delta_text for chunk in chunks if chunk.delta_text] == ["hi"]
    # The import failure lives only on the Responses API route; a request anywhere
    # else means this test no longer covers it.
    assert len(request_paths) == 1
    assert "/responses" in request_paths[0]
