"""Tests for litellm_model_info.reasoning_support and its lookup name.

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
from tables.utils.litellm_model_info import (
    NO_REASONING_SUPPORT,
    ReasoningSupport,
    litellm_lookup_name,
    reasoning_support,
)

SNAPSHOT_ONLY_MODEL = "epicstaff-snapshot-reasoner"


@pytest.fixture
def snapshot_path(monkeypatch, tmp_path_factory):
    path = tmp_path_factory.mktemp("litellm_snapshot") / "litellm_model_cost_snapshot.json"
    monkeypatch.setattr(litellm, "model_cost", dict(litellm.model_cost))
    monkeypatch.setenv("LITELLM_MODEL_COST_SNAPSHOT_PATH", str(path))
    monkeypatch.setattr(litellm_model_info, "_loaded_snapshot_mtime", None)
    monkeypatch.setattr(litellm_model_info, "_reasoning_support_cache", OrderedDict())
    monkeypatch.setattr(litellm_model_info, "_model_cost_key_index", {})
    # litellm caches lookups by model name, across the per-test model_cost copies.
    litellm.utils._invalidate_model_cost_lowercase_map()
    yield path
    litellm.utils._invalidate_model_cost_lowercase_map()


def test_missing_snapshot_uses_the_bundled_map(snapshot_path):
    assert reasoning_support("openai", "o3-mini").supports_reasoning is True
    assert reasoning_support("openai", "gpt-4o").supports_reasoning is False


def test_corrupt_snapshot_falls_back_to_the_bundled_map(snapshot_path):
    snapshot_path.write_text("{not json", encoding="utf-8")

    assert reasoning_support("openai", "o3-mini").supports_reasoning is True
    assert reasoning_support("openai", "gpt-4o").supports_reasoning is False


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

    assert reasoning_support("openai", SNAPSHOT_ONLY_MODEL).supports_reasoning is True


def test_newer_snapshot_invalidates_cached_answers(snapshot_path):
    assert reasoning_support("openai", SNAPSHOT_ONLY_MODEL).supports_reasoning is False

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

    assert reasoning_support("openai", SNAPSHOT_ONLY_MODEL).supports_reasoning is True


def test_provider_alias_is_applied(snapshot_path):
    assert litellm_lookup_name("google_ai", "gemini-2.5-pro") == "gemini/gemini-2.5-pro"
    assert reasoning_support("google_ai", "gemini-2.5-pro").supports_reasoning is True
    assert reasoning_support("google_ai", "gemini/gemini-2.5-pro").supports_reasoning is True


def test_azure_is_looked_up_by_model_name(snapshot_path):
    # The deployment id is never part of the lookup: callers pass LLMModel.name.
    assert litellm_lookup_name("azure", "o3-mini") == "azure/o3-mini"
    assert reasoning_support("azure", "o3-mini").supports_reasoning is True


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
    assert reasoning_support("openai", "epicstaff-no-such-model").supports_reasoning is False


def test_litellm_failure_answers_false(snapshot_path, monkeypatch):
    def raising_supports_reasoning(model):
        raise RuntimeError("model map broken")

    monkeypatch.setattr(litellm, "supports_reasoning", raising_supports_reasoning)

    assert reasoning_support("openai", "o3-mini") == NO_REASONING_SUPPORT


@pytest.fixture
def no_network(monkeypatch):
    def refuse_connection(self, address):
        raise AssertionError(f"reasoning_support opened a connection to {address}")

    monkeypatch.setattr(socket.socket, "connect", refuse_connection)


@pytest.fixture
def litellm_must_not_be_asked(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("litellm was asked instead of the static map")

    monkeypatch.setattr(litellm, "supports_reasoning", fail)
    monkeypatch.setattr(litellm, "get_model_info", fail)


@pytest.mark.parametrize("provider_name", ["ollama", "ollama_chat", "lemonade", "huggingface"])
def test_remote_lookup_model_missing_from_the_map_is_false_without_network(
    snapshot_path, no_network, litellm_must_not_be_asked, provider_name
):
    assert reasoning_support(provider_name, "epicstaff-local-only-model") == NO_REASONING_SUPPORT


@pytest.mark.parametrize("reasoning", [True, False])
def test_remote_lookup_model_in_the_map_uses_its_entry(
    snapshot_path, no_network, litellm_must_not_be_asked, reasoning
):
    litellm.model_cost["ollama/epicstaff-mapped-model"] = {
        "litellm_provider": "ollama",
        "mode": "chat",
        "supports_reasoning": reasoning,
    }

    assert reasoning_support("ollama", "epicstaff-mapped-model").supports_reasoning is reasoning


def test_remote_lookup_map_entry_is_matched_case_insensitively(
    snapshot_path, no_network, litellm_must_not_be_asked
):
    litellm.model_cost["huggingface/org/epicstaff-reasoner"] = {
        "litellm_provider": "huggingface",
        "mode": "chat",
        "supports_reasoning": True,
    }

    assert reasoning_support("huggingface", "huggingface/Org/EpicStaff-Reasoner").supports_reasoning is True


def test_cache_is_bounded_and_evicts_the_least_recently_used(snapshot_path, monkeypatch):
    monkeypatch.setattr(litellm_model_info, "REASONING_SUPPORT_CACHE_SIZE", 3)

    for index in range(5):
        reasoning_support("ollama", f"epicstaff-model-{index}")

    assert list(litellm_model_info._reasoning_support_cache) == [
        "ollama/epicstaff-model-2",
        "ollama/epicstaff-model-3",
        "ollama/epicstaff-model-4",
    ]


def test_cache_hit_refreshes_recency(snapshot_path, monkeypatch):
    monkeypatch.setattr(litellm_model_info, "REASONING_SUPPORT_CACHE_SIZE", 2)

    reasoning_support("ollama", "epicstaff-first")
    reasoning_support("ollama", "epicstaff-second")
    reasoning_support("ollama", "epicstaff-first")
    reasoning_support("ollama", "epicstaff-third")

    assert list(litellm_model_info._reasoning_support_cache) == [
        "ollama/epicstaff-first",
        "ollama/epicstaff-third",
    ]


def test_overlong_lookup_is_answered_but_not_cached(snapshot_path):
    overlong_name = "x" * (litellm_model_info.MAX_CACHED_LOOKUP_LENGTH + 1)

    assert reasoning_support("ollama", overlong_name).supports_reasoning is False
    assert len(litellm_model_info._reasoning_support_cache) == 0


def test_newer_snapshot_clears_the_cache(snapshot_path):
    reasoning_support("ollama", "epicstaff-cached")
    assert len(litellm_model_info._reasoning_support_cache) == 1

    snapshot_path.write_text(json.dumps({}), encoding="utf-8")
    reasoning_support("ollama", "epicstaff-other")

    assert list(litellm_model_info._reasoning_support_cache) == ["ollama/epicstaff-other"]


# Read off litellm's bundled map. Cross-checked against litellm's own request path,
# which refuses gpt-5-mini xhigh, gpt-5.4-mini minimal, gpt-5.5-pro low, Azure
# gpt-5-mini none and Claude Sonnet 4.6 / Gemini 2.5 xhigh before sending; OpenAI was
# checked by hand to answer 400 to "none" on gpt-5-mini and the o-series.
@pytest.mark.parametrize(
    "provider_name, model_name, expected",
    [
        ("openai", "gpt-5.4-mini", ["none", "low", "medium", "high", "xhigh"]),
        ("openai", "gpt-5-mini", ["minimal", "low", "medium", "high"]),
        (None, "gpt-5-mini", ["minimal", "low", "medium", "high"]),
        ("openai", "o3", ["low", "medium", "high"]),
        ("openai", "gpt-5.5-pro", ["medium", "high", "xhigh"]),
        ("anthropic", "claude-opus-4-8", ["none", "low", "medium", "high", "xhigh", "max"]),
        ("anthropic", "claude-sonnet-4-6", ["none", "low", "medium", "high", "max"]),
        ("google_ai", "gemini-2.5-flash", ["none", "low", "medium", "high"]),
        ("azure", "gpt-5-mini", ["minimal", "low", "medium", "high"]),
        ("azure", "gpt-5.4-mini", ["none", "low", "medium", "high", "xhigh"]),
        ("azure", "o3", ["low", "medium", "high"]),
        # litellm's get_model_info raises for Azure AI's OpenAI models; the azure_ai
        # entry, then the bare OpenAI entry, decide. Its own models keep "none".
        ("azure_ai", "gpt-5-mini", ["minimal", "low", "medium", "high"]),
        ("azure_ai", "gpt-5.4-mini", ["none", "low", "medium", "high", "xhigh"]),
        ("azure_ai", "o3", ["low", "medium", "high"]),
        ("azure_ai", "claude-sonnet-4-6", ["none", "low", "medium", "high", "max"]),
        ("azure_ai", "deepseek-r1", ["none", "low", "medium", "high"]),
        ("moonshot", "kimi-k3", ["low", "high", "max"]),
        ("openai", "gpt-4o", []),
    ],
)
def test_bundled_map_levels(snapshot_path, provider_name, model_name, expected):
    support = reasoning_support(provider_name, model_name)

    assert support.supports_reasoning is bool(expected)
    assert support.ordered_efforts() == expected


def _map_entry(provider, **fields):
    return {"litellm_provider": provider, "mode": "chat", "supports_reasoning": True, **fields}


def _efforts(provider, model="epicstaff-reasoner"):
    return set(reasoning_support(provider, model).efforts)


def test_ordered_efforts_runs_weakest_first():
    support = ReasoningSupport(True, frozenset({"max", "none", "high", "minimal"}))

    assert support.ordered_efforts() == ["none", "minimal", "high", "max"]


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_declared_levels_win_over_every_flag(snapshot_path, provider):
    litellm.model_cost[f"{provider}/epicstaff-reasoner"] = _map_entry(
        provider,
        reasoning_effort_levels=["low", "high", "max"],
        supports_none_reasoning_effort=True,
        supports_xhigh_reasoning_effort=True,
    )

    assert _efforts(provider) == {"low", "high", "max"}


def test_declared_levels_drop_unknown_values(snapshot_path):
    litellm.model_cost["openai/epicstaff-reasoner"] = _map_entry(
        "openai", reasoning_effort_levels=["low", "ultra"]
    )

    assert _efforts("openai") == {"low"}


def test_declared_empty_levels_leave_no_effort(snapshot_path):
    litellm.model_cost["openai/epicstaff-reasoner"] = _map_entry(
        "openai", reasoning_effort_levels=[]
    )

    assert reasoning_support("openai", "epicstaff-reasoner") == ReasoningSupport(True, frozenset())


@pytest.mark.parametrize(
    "provider, expected",
    [
        ("openai", {"low", "medium", "high"}),
        ("anthropic", {"none", "low", "medium", "high"}),
    ],
)
def test_unflagged_reasoning_model(snapshot_path, provider, expected):
    litellm.model_cost[f"{provider}/epicstaff-reasoner"] = _map_entry(provider)

    assert _efforts(provider) == expected


@pytest.mark.parametrize("low_flag, expected_low", [(False, False), (True, True)])
def test_low_is_dropped_only_by_a_false_flag(snapshot_path, low_flag, expected_low):
    litellm.model_cost["anthropic/epicstaff-reasoner"] = _map_entry(
        "anthropic", supports_low_reasoning_effort=low_flag
    )

    assert ("low" in _efforts("anthropic")) is expected_low
    assert {"medium", "high"} <= _efforts("anthropic")


@pytest.mark.parametrize(
    "provider, none_flag, expected",
    [
        ("openai", True, True),
        ("openai", False, False),
        ("openai", None, False),
        ("anthropic", True, True),
        ("anthropic", False, False),
        ("anthropic", None, True),
    ],
)
def test_none_follows_the_flag_then_the_provider(snapshot_path, provider, none_flag, expected):
    fields = {} if none_flag is None else {"supports_none_reasoning_effort": none_flag}
    litellm.model_cost[f"{provider}/epicstaff-reasoner"] = _map_entry(provider, **fields)

    assert ("none" in _efforts(provider)) is expected


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
@pytest.mark.parametrize(
    "level, flag",
    [
        ("minimal", "supports_minimal_reasoning_effort"),
        ("xhigh", "supports_xhigh_reasoning_effort"),
        ("max", "supports_max_reasoning_effort"),
    ],
)
@pytest.mark.parametrize("flag_value, expected", [(True, True), (False, False), (None, False)])
def test_opt_in_level_needs_a_true_flag_for_every_provider(
    snapshot_path, provider, level, flag, flag_value, expected
):
    fields = {} if flag_value is None else {flag: flag_value}
    litellm.model_cost[f"{provider}/epicstaff-reasoner"] = _map_entry(provider, **fields)

    assert (level in _efforts(provider)) is expected


@pytest.mark.parametrize("provider", ["azure", "azure_ai"])
@pytest.mark.parametrize(
    "openai_fields, expected",
    [
        ({"supports_none_reasoning_effort": True}, {"none", "low", "medium", "high"}),
        ({"supports_none_reasoning_effort": False}, {"low", "medium", "high"}),
        ({}, {"low", "medium", "high"}),
        ({"supports_minimal_reasoning_effort": True}, {"minimal", "low", "medium", "high"}),
        ({"supports_xhigh_reasoning_effort": True}, {"low", "medium", "high", "xhigh"}),
        ({"supports_max_reasoning_effort": True}, {"low", "medium", "high", "max"}),
        ({"supports_low_reasoning_effort": False}, {"medium", "high"}),
        ({"reasoning_effort_levels": ["low", "high"]}, {"low", "high"}),
    ],
)
def test_azure_without_a_field_falls_back_to_the_openai_entry(
    snapshot_path, provider, openai_fields, expected
):
    litellm.model_cost[f"{provider}/epicstaff-reasoner"] = _map_entry(provider)
    litellm.model_cost["epicstaff-reasoner"] = _map_entry("openai", **openai_fields)

    assert _efforts(provider) == expected


@pytest.mark.parametrize("provider", ["azure", "azure_ai"])
def test_azure_fields_win_over_the_openai_entry(snapshot_path, provider):
    litellm.model_cost[f"{provider}/epicstaff-reasoner"] = _map_entry(
        provider, supports_none_reasoning_effort=False, supports_xhigh_reasoning_effort=False
    )
    litellm.model_cost["epicstaff-reasoner"] = _map_entry(
        "openai", supports_none_reasoning_effort=True, supports_xhigh_reasoning_effort=True
    )

    assert _efforts(provider) == {"low", "medium", "high"}


@pytest.mark.parametrize(
    "provider, expected",
    # Azure serves OpenAI's models only: without any flag "none" stays refused.
    [("azure", {"low", "medium", "high"}), ("azure_ai", {"none", "low", "medium", "high"})],
)
def test_azure_without_an_openai_entry_follows_the_provider(snapshot_path, provider, expected):
    litellm.model_cost[f"{provider}/epicstaff-reasoner"] = _map_entry(provider)

    assert _efforts(provider) == expected


def test_azure_ai_ignores_a_bare_entry_of_another_vendor(snapshot_path):
    litellm.model_cost["azure_ai/epicstaff-reasoner"] = _map_entry("azure_ai")
    litellm.model_cost["epicstaff-reasoner"] = _map_entry(
        "anthropic", supports_none_reasoning_effort=False, supports_max_reasoning_effort=True
    )

    assert _efforts("azure_ai") == {"none", "low", "medium", "high"}


def test_model_info_failure_reads_the_flags_from_the_map_entry(snapshot_path, monkeypatch):
    # The shape of litellm's answer for azure_ai/<OpenAI model>: get_model_info raises
    # although the azure_ai entry exists.
    litellm.model_cost["azure_ai/epicstaff-reasoner"] = _map_entry(
        "azure_ai", supports_none_reasoning_effort=False, supports_xhigh_reasoning_effort=True
    )
    litellm.model_cost["epicstaff-reasoner"] = _map_entry(
        "openai", supports_none_reasoning_effort=True
    )

    def raising_get_model_info(model):
        raise RuntimeError("model not mapped")

    monkeypatch.setattr(litellm, "get_model_info", raising_get_model_info)

    assert _efforts("azure_ai") == {"low", "medium", "high", "xhigh"}


def test_model_info_failure_counts_as_missing_flags(snapshot_path, monkeypatch):
    def raising_get_model_info(model):
        raise RuntimeError("model map broken")

    monkeypatch.setattr(litellm, "get_model_info", raising_get_model_info)

    assert reasoning_support("openai", "o3-mini").ordered_efforts() == ["low", "medium", "high"]
    assert reasoning_support("anthropic", "claude-sonnet-4-6").ordered_efforts() == [
        "none",
        "low",
        "medium",
        "high",
    ]


@pytest.mark.parametrize(
    "fields, expected",
    [
        ({}, {"none", "low", "medium", "high"}),
        ({"supports_none_reasoning_effort": False}, {"low", "medium", "high"}),
        (
            {"supports_xhigh_reasoning_effort": True, "supports_max_reasoning_effort": True},
            {"none", "low", "medium", "high", "xhigh", "max"},
        ),
        ({"reasoning_effort_levels": ["minimal", "high"]}, {"minimal", "high"}),
    ],
)
def test_remote_lookup_levels_come_from_the_static_entry(
    snapshot_path, no_network, litellm_must_not_be_asked, fields, expected
):
    litellm.model_cost["ollama/epicstaff-mapped-model"] = _map_entry("ollama", **fields)

    assert _efforts("ollama", "epicstaff-mapped-model") == expected


def test_cached_answer_carries_the_levels(snapshot_path, monkeypatch):
    litellm.model_cost["openai/epicstaff-reasoner"] = _map_entry(
        "openai", supports_xhigh_reasoning_effort=True
    )
    first = reasoning_support("openai", "epicstaff-reasoner")

    def fail(*args, **kwargs):
        raise AssertionError("litellm was asked for a cached answer")

    monkeypatch.setattr(litellm, "supports_reasoning", fail)
    monkeypatch.setattr(litellm, "get_model_info", fail)

    assert reasoning_support("openai", "epicstaff-reasoner") == first
    assert first.ordered_efforts() == ["low", "medium", "high", "xhigh"]


def test_answer_computed_while_a_newer_snapshot_loads_is_not_cached(snapshot_path, monkeypatch):
    litellm.model_cost["openai/epicstaff-reasoner"] = _map_entry(
        "openai", supports_xhigh_reasoning_effort=True
    )
    real_get_model_info = litellm.get_model_info

    def get_model_info_racing_a_snapshot_load(model, *args, **kwargs):
        info = real_get_model_info(model, *args, **kwargs)
        if model == "openai/epicstaff-reasoner":
            monkeypatch.setattr(litellm, "get_model_info", real_get_model_info)
            snapshot_path.write_text(
                json.dumps(
                    {
                        "openai/epicstaff-reasoner": _map_entry(
                            "openai", supports_xhigh_reasoning_effort=False
                        )
                    }
                ),
                encoding="utf-8",
            )
            # Another request loads the newer snapshot while this lookup is in flight.
            reasoning_support("ollama", "epicstaff-other")
        return info

    monkeypatch.setattr(litellm, "get_model_info", get_model_info_racing_a_snapshot_load)

    in_flight_answer = reasoning_support("openai", "epicstaff-reasoner")

    assert "xhigh" in in_flight_answer.efforts
    assert _efforts("openai") == {"low", "medium", "high"}


def test_newer_snapshot_changes_the_levels_litellm_reports(snapshot_path):
    # get_model_info answers from an LRU cache keyed by model name; without the
    # invalidation the second call would still see xhigh.
    litellm.model_cost["openai/epicstaff-reasoner"] = _map_entry(
        "openai", supports_xhigh_reasoning_effort=True
    )
    assert "xhigh" in _efforts("openai")

    snapshot_path.write_text(
        json.dumps(
            {
                "openai/epicstaff-reasoner": _map_entry(
                    "openai", supports_xhigh_reasoning_effort=False
                )
            }
        ),
        encoding="utf-8",
    )

    assert _efforts("openai") == {"low", "medium", "high"}
