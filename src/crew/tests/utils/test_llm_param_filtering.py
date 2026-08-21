import types

import pytest

from crewai.agent import temporary_temperature
from src.crew.utils.llm_wrapper import PatchedLLM, _strip_trailing_assistant


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
    _call("anthropic/claude-opus-4-8", stop=["\nObservation"])
    assert "stop" in capture_completion
    assert "\nObservation" in capture_completion["stop"]


@pytest.mark.parametrize("model", ["o3", "o4-mini"])
def test_supports_stop_words_false_for_o_series(model):
    llm = PatchedLLM(model=model, api_key="test-key")
    assert llm.supports_stop_words() is False


def test_supports_stop_words_true_for_claude_4x():
    llm = PatchedLLM(model="anthropic/claude-opus-4-8", api_key="test-key")
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


# --- _strip_trailing_assistant (claude 4.x prefill handling) ---


def test_strip_raises_on_empty_messages():
    with pytest.raises(ValueError):
        _strip_trailing_assistant([])


def test_strip_noop_when_last_not_assistant():
    messages = [{"role": "user", "content": "hi"}]
    result = _strip_trailing_assistant(messages)
    assert result == messages


def test_strip_string_content_empty():
    result = _strip_trailing_assistant([{"role": "assistant", "content": ""}])
    assert result[-1]["role"] == "user"
    assert (
        result[-1]["content"]
        == "Continue from where you left off and provide your response."
    )
    assert "partial progress" not in result[-1]["content"]


def test_strip_string_content_nonempty():
    result = _strip_trailing_assistant([{"role": "assistant", "content": "partial"}])
    assert result[-1]["role"] == "user"
    assert "partial progress" in result[-1]["content"]
    assert "partial" in result[-1]["content"]


def test_strip_list_text_only():
    content = [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]
    result = _strip_trailing_assistant([{"role": "assistant", "content": content}])
    assert "A\nB" in result[-1]["content"]


def test_strip_list_non_text_only():
    content = [{"type": "image"}, {"type": "tool_use", "id": "x"}]
    result = _strip_trailing_assistant([{"role": "assistant", "content": content}])
    assert result[-1]["content"].count("[non-text content]") == 1


def test_strip_list_mixed():
    content = [
        {"type": "text", "text": "A"},
        {"type": "tool_use"},
        {"type": "text", "text": "B"},
    ]
    result = _strip_trailing_assistant([{"role": "assistant", "content": content}])
    assert "A\n[non-text content]\nB" in result[-1]["content"]


def test_strip_list_empty_content():
    result = _strip_trailing_assistant([{"role": "assistant", "content": []}])
    assert result[-1]["role"] == "user"
    assert (
        result[-1]["content"]
        == "Continue from where you left off and provide your response."
    )
    assert "partial progress" not in result[-1]["content"]


def test_strip_preserves_prior_messages():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "assistant", "content": "third"},
    ]
    result = _strip_trailing_assistant(messages)
    assert result[0] == {"role": "user", "content": "first"}
    assert result[1] == {"role": "assistant", "content": "second"}
    assert result[-1]["role"] == "user"


def test_strip_list_text_block_with_none_value():
    """Text block with text=None must not raise — treated as empty string."""
    messages = [{"role": "assistant", "content": [{"type": "text", "text": None}]}]
    result = _strip_trailing_assistant(messages)
    assert result[-1]["role"] == "user"
    assert "partial progress" not in result[-1]["content"]


def test_patched_llm_strips_list_content_before_completion(capture_completion):
    messages = [
        {"role": "user", "content": "Do the task."},
        {"role": "assistant", "content": [{"type": "text", "text": "partial"}]},
    ]
    llm = PatchedLLM(model="claude-opus-4-8", api_key="test-key")
    llm.call(messages)
    assert capture_completion["messages"][-1]["role"] == "user"
    assert "partial" in capture_completion["messages"][-1]["content"]
