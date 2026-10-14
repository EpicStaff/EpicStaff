"""Tests for litellm_model_info.supports_reasoning and its lookup name.

litellm.model_cost is replaced by a copy per test, so merging a snapshot never
leaks into other tests. The snapshot lives in a fresh directory per test:
tests/conftest.py overrides tmp_path with one directory shared by every test.
"""

import json
import socket
from collections import OrderedDict

import litellm
import pytest

from tables.utils import litellm_model_info
from tables.utils.litellm_model_info import litellm_lookup_name, supports_reasoning

SNAPSHOT_ONLY_MODEL = "epicstaff-snapshot-reasoner"


@pytest.fixture
def snapshot_path(monkeypatch, tmp_path_factory):
    path = tmp_path_factory.mktemp("litellm_snapshot") / "litellm_model_cost_snapshot.json"
    monkeypatch.setattr(litellm, "model_cost", dict(litellm.model_cost))
    monkeypatch.setenv("LITELLM_MODEL_COST_SNAPSHOT_PATH", str(path))
    monkeypatch.setattr(litellm_model_info, "_loaded_snapshot_mtime", None)
    monkeypatch.setattr(litellm_model_info, "_reasoning_support_cache", OrderedDict())
    monkeypatch.setattr(litellm_model_info, "_model_cost_key_index", {})
    yield path


def test_missing_snapshot_uses_the_bundled_map(snapshot_path):
    assert supports_reasoning("openai", "o3-mini") is True
    assert supports_reasoning("openai", "gpt-4o") is False


def test_corrupt_snapshot_falls_back_to_the_bundled_map(snapshot_path):
    snapshot_path.write_text("{not json", encoding="utf-8")

    assert supports_reasoning("openai", "o3-mini") is True
    assert supports_reasoning("openai", "gpt-4o") is False


def test_snapshot_entries_are_used(snapshot_path):
    snapshot_path.write_text(
        json.dumps(
            {
                f"openai/{SNAPSHOT_ONLY_MODEL}": {
                    "litellm_provider": "openai",
                    "mode": "chat",
                    "supports_reasoning": True,
                }
            }
        ),
        encoding="utf-8",
    )

    assert supports_reasoning("openai", SNAPSHOT_ONLY_MODEL) is True


def test_newer_snapshot_invalidates_cached_answers(snapshot_path):
    assert supports_reasoning("openai", SNAPSHOT_ONLY_MODEL) is False

    snapshot_path.write_text(
        json.dumps(
            {
                f"openai/{SNAPSHOT_ONLY_MODEL}": {
                    "litellm_provider": "openai",
                    "mode": "chat",
                    "supports_reasoning": True,
                }
            }
        ),
        encoding="utf-8",
    )

    assert supports_reasoning("openai", SNAPSHOT_ONLY_MODEL) is True


def test_provider_alias_is_applied(snapshot_path):
    assert litellm_lookup_name("google_ai", "gemini-2.5-pro") == "gemini/gemini-2.5-pro"
    assert supports_reasoning("google_ai", "gemini-2.5-pro") is True
    assert supports_reasoning("google_ai", "gemini/gemini-2.5-pro") is True


def test_azure_is_looked_up_by_model_name(snapshot_path):
    # The deployment id is never part of the lookup: callers pass LLMModel.name.
    assert litellm_lookup_name("azure", "o3-mini") == "azure/o3-mini"
    assert supports_reasoning("azure", "o3-mini") is True


@pytest.mark.parametrize(
    "provider_name, model_name, expected",
    [
        (None, "gpt-4o", "gpt-4o"),
        ("", "gpt-4o", "gpt-4o"),
        (" OpenAI ", "gpt-4o", "openai/gpt-4o"),
        ("ollama", "ollama/mistral", "ollama/mistral"),
        ("groq", "openai/gpt-oss-120b", "groq/openai/gpt-oss-120b"),
    ],
)
def test_lookup_name(provider_name, model_name, expected):
    assert litellm_lookup_name(provider_name, model_name) == expected


def test_unknown_model_is_not_a_reasoning_model(snapshot_path):
    assert supports_reasoning("openai", "epicstaff-no-such-model") is False


def test_litellm_failure_answers_false(snapshot_path, monkeypatch):
    def raising_supports_reasoning(model):
        raise RuntimeError("model map broken")

    monkeypatch.setattr(litellm, "supports_reasoning", raising_supports_reasoning)

    assert supports_reasoning("openai", "o3-mini") is False


@pytest.fixture
def no_network(monkeypatch):
    def refuse_connection(self, address):
        raise AssertionError(f"supports_reasoning opened a connection to {address}")

    monkeypatch.setattr(socket.socket, "connect", refuse_connection)


@pytest.fixture
def litellm_must_not_be_asked(monkeypatch):
    def fail(**kwargs):
        raise AssertionError("litellm.supports_reasoning was called")

    monkeypatch.setattr(litellm, "supports_reasoning", fail)


@pytest.mark.parametrize("provider_name", ["ollama", "ollama_chat", "lemonade", "huggingface"])
def test_remote_lookup_model_missing_from_the_map_is_false_without_network(
    snapshot_path, no_network, litellm_must_not_be_asked, provider_name
):
    assert supports_reasoning(provider_name, "epicstaff-local-only-model") is False


@pytest.mark.parametrize("reasoning", [True, False])
def test_remote_lookup_model_in_the_map_uses_its_entry(
    snapshot_path, no_network, litellm_must_not_be_asked, reasoning
):
    litellm.model_cost["ollama/epicstaff-mapped-model"] = {
        "litellm_provider": "ollama",
        "mode": "chat",
        "supports_reasoning": reasoning,
    }

    assert supports_reasoning("ollama", "epicstaff-mapped-model") is reasoning


def test_remote_lookup_map_entry_is_matched_case_insensitively(
    snapshot_path, no_network, litellm_must_not_be_asked
):
    litellm.model_cost["huggingface/org/epicstaff-reasoner"] = {
        "litellm_provider": "huggingface",
        "mode": "chat",
        "supports_reasoning": True,
    }

    assert supports_reasoning("huggingface", "huggingface/Org/EpicStaff-Reasoner") is True


def test_cache_is_bounded_and_evicts_the_least_recently_used(snapshot_path, monkeypatch):
    monkeypatch.setattr(litellm_model_info, "REASONING_SUPPORT_CACHE_SIZE", 3)

    for index in range(5):
        supports_reasoning("ollama", f"epicstaff-model-{index}")

    assert list(litellm_model_info._reasoning_support_cache) == [
        "ollama/epicstaff-model-2",
        "ollama/epicstaff-model-3",
        "ollama/epicstaff-model-4",
    ]


def test_cache_hit_refreshes_recency(snapshot_path, monkeypatch):
    monkeypatch.setattr(litellm_model_info, "REASONING_SUPPORT_CACHE_SIZE", 2)

    supports_reasoning("ollama", "epicstaff-first")
    supports_reasoning("ollama", "epicstaff-second")
    supports_reasoning("ollama", "epicstaff-first")
    supports_reasoning("ollama", "epicstaff-third")

    assert list(litellm_model_info._reasoning_support_cache) == [
        "ollama/epicstaff-first",
        "ollama/epicstaff-third",
    ]


def test_overlong_lookup_is_answered_but_not_cached(snapshot_path):
    overlong_name = "x" * (litellm_model_info.MAX_CACHED_LOOKUP_LENGTH + 1)

    assert supports_reasoning("ollama", overlong_name) is False
    assert len(litellm_model_info._reasoning_support_cache) == 0


def test_newer_snapshot_clears_the_cache(snapshot_path):
    supports_reasoning("ollama", "epicstaff-cached")
    assert len(litellm_model_info._reasoning_support_cache) == 1

    snapshot_path.write_text(json.dumps({}), encoding="utf-8")
    supports_reasoning("ollama", "epicstaff-other")

    assert list(litellm_model_info._reasoning_support_cache) == ["ollama/epicstaff-other"]
