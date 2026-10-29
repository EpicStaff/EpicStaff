"""Picture tool: config field supplies the OpenAI API key.

The tool runs in the sandbox, invoked by an agent; the `args_schema.json`
config fields arrive as module-level globals via `global_kwargs`. These tests
verify that config fields correctly configure the tool and handle errors
gracefully.
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from conftest import TOOLS_ROOT, load_tool_main

# picture_tool/main.py imports openai at module level. Per its
# requirements.txt, openai is installed into this tool's own dedicated venv by
# the sandbox at execution time, not into any service venv -- skip cleanly
# instead of failing when running these tests outside that venv.
pytest.importorskip(
    "openai",
    reason="installed by the sandbox into this tool's own venv, not a service venv",
)

PROMPT = "a red cube on a white table"


class FakeImages:
    def __init__(self, urls: list[str | None]):
        self._urls = urls
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(url=url) for url in self._urls])


class FakeOpenAI:
    """Stand-in for the `OpenAI` class, recording every api_key it is built with."""

    def __init__(self, urls: list[str | None] | None = None):
        self.api_keys: list[str] = []
        self.images = FakeImages(urls if urls is not None else ["https://img/1.png"])

    def __call__(self, *, api_key: str):
        self.api_keys.append(api_key)
        return self


def load_picture_tool(**injected_globals: Any):
    module = load_tool_main("picture_tool")
    for name, value in injected_globals.items():
        setattr(module, name, value)
    return module


def test_config_field_supplies_the_api_key():
    module = load_picture_tool(api_key="sk-from-config")
    fake_openai = FakeOpenAI()

    with patch.object(module, "OpenAI", fake_openai):
        module.main(PROMPT)

    assert fake_openai.api_keys == ["sk-from-config"]


def test_missing_api_key_is_returned_as_an_error_string():
    module = load_picture_tool()
    fake_openai = FakeOpenAI()

    with patch.object(module, "OpenAI", fake_openai):
        result = module.main(PROMPT)

    assert result.startswith("Error executing tool: ")
    assert "api_key" in result
    assert fake_openai.api_keys == []


def test_generation_failure_is_returned_as_an_error_string_without_leaking_its_content():
    module = load_picture_tool(api_key="sk-from-config")
    fake_openai = FakeOpenAI()

    def raise_rate_limit(**kwargs):
        # The message below stands in for whatever a real SDK error might
        # embed (e.g. request details) -- it must never reach the result.
        raise ConnectionError("rate limited, key=sk-from-config")

    fake_openai.images.generate = raise_rate_limit

    with patch.object(module, "OpenAI", fake_openai):
        result = module.main(PROMPT)

    assert result == "Failed to generate image: ConnectionError"
    assert "sk-from-config" not in result


def test_images_without_a_url_are_dropped_from_the_result():
    module = load_picture_tool(api_key="sk-from-config")
    fake_openai = FakeOpenAI(urls=["https://img/1.png", None])

    with patch.object(module, "OpenAI", fake_openai):
        result = module.main(PROMPT, n=2)

    assert result == ["https://img/1.png"]


def test_stray_config_kwarg_is_absorbed_and_global_wins():
    """Regression test: python_code.global_kwargs folds user_input config
    (api_key) into func_kwargs, so main() may also receive it as a kwarg.
    The global remains the source of truth; the stray kwarg must be
    swallowed by **kwargs without a TypeError."""
    module = load_picture_tool(api_key="real-key")
    fake_openai = FakeOpenAI()

    with patch.object(module, "OpenAI", fake_openai):
        module.main(PROMPT, api_key="stray-kwarg-key")

    assert fake_openai.api_keys == ["real-key"]


def test_the_agent_can_neither_see_nor_set_the_api_key():
    schema = json.loads((TOOLS_ROOT / "picture_tool" / "args_schema.json").read_text())

    assert schema["properties"]["api_key"]["input_type"] == "user_input"
    assert "api_key" in schema["required"]
