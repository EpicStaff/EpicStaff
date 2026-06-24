import types

import pytest

from crewai.agent import temporary_temperature
from src.crew.utils.llm_wrapper import PatchedLLM


def _fake_stream():
    yield {
        "choices": [{"delta": {"content": "ok"}}],
    }


@pytest.fixture
def capture_completion(monkeypatch):
    """Patch litellm.completion to capture the params crewai passes in."""
    import litellm

    captured = {}

    def _fake_completion(**params):
        captured.clear()
        captured.update(params)
        return _fake_stream()

    monkeypatch.setattr(litellm, "completion", _fake_completion)
    return captured


def _call(model: str, **kwargs) -> dict:
    llm = PatchedLLM(model=model, api_key="test-key", **kwargs)
    llm.call("Reply with a single word: ok")
    return llm


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
    ],
)
def test_claude_4x_drops_temperature(model, capture_completion):
    _call(model, temperature=0.7)
    assert "temperature" not in capture_completion
    assert "top_p" not in capture_completion


@pytest.mark.parametrize("model", ["o3", "o4-mini", "o1"])
def test_o_series_drops_temperature(model, capture_completion):
    _call(model, temperature=0.7)
    assert "temperature" not in capture_completion


@pytest.mark.parametrize("model", ["gpt-4o", "gpt-4", "claude-3-5-sonnet"])
def test_normal_models_preserve_temperature(model, capture_completion):
    _call(model, temperature=0.7)
    assert capture_completion["temperature"] == 0.7


@pytest.mark.parametrize(
    "model",
    ["o3", "o4-mini", "o3-2025-04-16", "o4-mini-2025-04-16"],
)
def test_o_series_drops_stop(model, capture_completion):
    _call(model, stop=["\nObservation"])
    assert "stop" not in capture_completion


def test_gpt_4o_preserves_stop(capture_completion):
    """The ReAct loop depends on the \\nObservation stop word."""
    _call("gpt-4o", stop=["\nObservation"])
    assert "stop" in capture_completion
    assert "\nObservation" in capture_completion["stop"]


def test_claude_4x_preserves_stop(capture_completion):
    """Claude 4.x drops temperature but MUST keep stop words."""
    _call("claude-opus-4-8", stop=["\nObservation"])
    assert "stop" in capture_completion
    assert "\nObservation" in capture_completion["stop"]


@pytest.mark.parametrize("model", ["o3", "o4-mini"])
def test_supports_stop_words_false_for_o_series(model):
    llm = PatchedLLM(model=model, api_key="test-key")
    assert llm.supports_stop_words() is False


def test_supports_stop_words_true_for_claude_4x():
    llm = PatchedLLM(model="claude-opus-4-8", api_key="test-key")
    assert llm.supports_stop_words() is True


# --- temporary_temperature (knowledge query path) ---


def test_temporary_temperature_noop_when_temperature_is_none():
    """PatchedLLM sets temperature=None for claude-4.x; temporary_temperature must not reintroduce it."""
    llm = types.SimpleNamespace(temperature=None)
    with temporary_temperature(llm, temp=0.0):
        assert llm.temperature is None
    assert llm.temperature is None


def test_temporary_temperature_sets_and_restores():
    llm = types.SimpleNamespace(temperature=0.7)
    with temporary_temperature(llm, temp=0.0):
        assert llm.temperature == 0.0
    assert llm.temperature == 0.7


def test_temporary_temperature_noop_when_no_attribute():
    llm = types.SimpleNamespace()
    with temporary_temperature(llm, temp=0.0):
        pass


def test_claude_4x_knowledge_path_never_sends_temperature(capture_completion):
    """Regression: PatchedLLM + temporary_temperature must not leak temperature=0.0 for claude-4.x."""
    llm = PatchedLLM(model="claude-opus-4-8", api_key="test-key")
    with temporary_temperature(llm, temp=0.0):
        llm.call("Reply with a single word: ok")
    assert "temperature" not in capture_completion
