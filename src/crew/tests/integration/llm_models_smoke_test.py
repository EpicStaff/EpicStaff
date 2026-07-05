import json
import os
from pathlib import Path

import litellm
import pytest

from src.crew.utils.llm_wrapper import _model_drops_temperature


MODELS_JSON_PATH = (
    Path(__file__).resolve().parents[3]
    / "django_app/tables/provider_models/llm_models.json"
)

TRANSIENT_ERRORS = (
    litellm.RateLimitError,
    litellm.InternalServerError,
    litellm.ServiceUnavailableError,
)


def _load_models(provider: str) -> list[str]:
    with open(MODELS_JSON_PATH) as f:
        data = json.load(f)
    return [m["name"] for m in data.get(provider, [])]


def _call_model(model: str, api_key: str) -> str:
    max_tokens = 1000 if _model_drops_temperature(model) else 200
    params = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with a single word: ok"}],
        "api_key": api_key,
        "max_tokens": max_tokens,
        "stream": False,
        "temperature": 0.0,
    }
    if _model_drops_temperature(model):
        del params["temperature"]

    response = litellm.completion(**params)
    return response.choices[0].message.content or ""


# NOTE: api keys are passed via environment variables and must not be hardcoded
# anywhere in the codebase. If the key is not found, the test is skipped.
@pytest.mark.parametrize("model", _load_models("anthropic"))
def test_anthropic_model(model):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    try:
        response = _call_model(model=model, api_key=api_key)
        assert response
    except TRANSIENT_ERRORS as e:
        pytest.skip(f"Transient provider error for {model}: {e}")


@pytest.mark.parametrize("model", _load_models("openai"))
def test_openai_model(model):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")
    try:
        response = _call_model(model=model, api_key=api_key)
        assert response
    except TRANSIENT_ERRORS as e:
        pytest.skip(f"Transient provider error for {model}: {e}")


@pytest.mark.parametrize("model", _load_models("gemini"))
def test_gemini_model(model):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set")
    try:
        response = _call_model(model=model, api_key=api_key)
        assert response
    except TRANSIENT_ERRORS as e:
        pytest.skip(f"Transient provider error for {model}: {e}")
