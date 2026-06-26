import os

import litellm
import pytest

from src.crew.utils.llm_wrapper import PatchedLLM

TRANSIENT_ERRORS = (
    litellm.RateLimitError,
    litellm.InternalServerError,
    litellm.ServiceUnavailableError,
)

PROMPT = "Reply with a single word: ok"


def _call_via_patched_llm(model: str, api_key: str) -> None:
    llm = PatchedLLM(model=model, api_key=api_key, max_tokens=500)
    llm.call(PROMPT)


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
    ],
)
def test_anthropic_claude4_no_temperature_error(model):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    try:
        _call_via_patched_llm(model=model, api_key=api_key)
    except TRANSIENT_ERRORS as e:
        pytest.skip(f"Transient provider error: {e}")


@pytest.mark.parametrize(
    "model",
    [
        "o3",
        "o4-mini",
        "o3-2025-04-16",
        "o4-mini-2025-04-16",
    ],
)
def test_openai_o_series_no_stop_error(model):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")
    try:
        _call_via_patched_llm(model=model, api_key=api_key)
    except TRANSIENT_ERRORS as e:
        pytest.skip(f"Transient provider error: {e}")


def test_gpt4o_control():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")
    try:
        _call_via_patched_llm(model="gpt-4o", api_key=api_key)
    except TRANSIENT_ERRORS as e:
        pytest.skip(f"Transient provider error: {e}")
