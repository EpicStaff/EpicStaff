import types

import pytest

pytest.importorskip(
    "psycopg",
    reason="requires libpq; only available in the Linux/Docker image, not this Windows venv",
    exc_type=ImportError,  # psycopg is installed but fails at import time without libpq
)

from domain.enums import SlotEnum  # noqa: E402
from infrastructure.database.mappers.graph import (  # noqa: E402
    graph_rag_orm_to_graphrag_config,
    graph_rag_orm_to_pricing_config,
)


def _make_fake_rag(
    *,
    rag_id: int = 1,
    slot: SlotEnum = SlotEnum.A,
    provider_name: str = "openai",
    model_name: str = "gpt-4o",
    without_index_config: bool = False,
    **llm_config_fields,
) -> types.SimpleNamespace:
    """Build a minimal fake GraphRag ORM row with the fields _to_graph_rag_config reads."""
    provider = types.SimpleNamespace(name=provider_name)
    llm_model = types.SimpleNamespace(
        name=model_name,
        llm_provider=provider,
        base_url=None,
        api_version=None,
    )
    llm_config = types.SimpleNamespace(
        **{
            "id": 1,
            "temperature": 0.5,
            "top_p": None,
            "stop": None,
            "max_tokens": None,
            "presence_penalty": None,
            "frequency_penalty": None,
            "logit_bias": None,
            "seed": None,
            "timeout": None,
            "reasoning_effort": None,
            "api_key": "sk-test",
            "input_cost_per_token": 0.000002,
            "output_cost_per_token": 0.00001,
            "model": llm_model,
            **llm_config_fields,
        }
    )

    embedding_provider = types.SimpleNamespace(name="openai")
    embedding_model = types.SimpleNamespace(
        name="text-embedding-ada-002",
        embedding_provider=embedding_provider,
        base_url=None,
    )
    embedding_config = types.SimpleNamespace(
        api_key="sk-test",
        model=embedding_model,
    )

    index_config = types.SimpleNamespace(
        chunk_strategy="tokens",
        chunk_size=1200,
        chunk_overlap=100,
        entity_types=["organization", "person"],
        max_gleanings=1,
        max_cluster_size=10,
    )

    return types.SimpleNamespace(
        graph_rag_id=rag_id,
        slot=slot,
        llm=llm_config,
        embedder=embedding_config,
        index_config=None if without_index_config else index_config,
    )


@pytest.mark.parametrize(
    "slot, expected_output_subdir, expected_lancedb_subdir",
    [
        (SlotEnum.A, "/a/output", "/a/lancedb"),
        (SlotEnum.B, "/b/output", "/b/lancedb"),
    ],
    ids=["slot_a", "slot_b"],
)
def test_config_points_at_the_requested_slot_of_this_rag(
    slot, expected_output_subdir, expected_lancedb_subdir
):
    """The row is on slot A; a reindex asks for B, and must never write into A."""
    rag = _make_fake_rag(rag_id=42, slot=SlotEnum.A)

    config = graph_rag_orm_to_graphrag_config(rag, slot=slot)

    assert "rag_42" in config.output_storage.prefix
    assert expected_output_subdir in config.output_storage.prefix
    assert expected_lancedb_subdir in config.vector_store.db_uri
    # graphrag's validator fills the schema; without it indexing fails with a KeyError.
    assert "entity_description" in config.vector_store.index_schema


def test_pricing_is_built_for_a_rag_without_index_config():
    """Pricing only needs the llm and embedder; an unset index config must not hide it."""
    rag = _make_fake_rag(without_index_config=True)

    pricing = graph_rag_orm_to_pricing_config(rag)

    assert pricing.llm_provider == "openai"
    assert pricing.llm_model == "gpt-4o"
    assert pricing.input_cost_per_token == 0.000002
    assert pricing.output_cost_per_token == 0.00001
    assert pricing.embedding.model == "text-embedding-ada-002"


def _completion_call_args(**llm_config_fields) -> dict:
    rag = _make_fake_rag(**llm_config_fields)
    config = graph_rag_orm_to_graphrag_config(rag, slot=SlotEnum.A)
    return config.completion_models["default_completion_model"].call_args


def test_completion_call_args_drop_sampling_params_anthropic_rejects_with_thinking():
    call_args = _completion_call_args(
        provider_name="anthropic",
        model_name="claude-sonnet-4-6",
        temperature=0.5,
        top_p=0.9,
        reasoning_effort="high",
    )

    assert call_args == {"reasoning_effort": "high"}


def test_completion_call_args_carry_reasoning_effort_and_generation_params():
    call_args = _completion_call_args(
        temperature=0.2,
        top_p=0.9,
        max_tokens=2048,
        presence_penalty=0.1,
        frequency_penalty=0.3,
        logit_bias={"50256": -100},
        seed=11,
        reasoning_effort="low",
    )

    assert call_args == {
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 2048,
        "presence_penalty": 0.1,
        "frequency_penalty": 0.3,
        "logit_bias": {50256: -100.0},
        "seed": 11,
        "reasoning_effort": "low",
    }


def test_completion_call_args_omit_unset_params():
    call_args = _completion_call_args(temperature=None)

    assert call_args == {}


def test_completion_call_args_never_carry_stop_or_timeout():
    call_args = _completion_call_args(stop=["Observation:"], timeout=120.0)

    assert "stop" not in call_args
    assert "timeout" not in call_args
    assert call_args == {"temperature": 0.5}


def test_completion_call_args_ignore_malformed_stop():
    call_args = _completion_call_args(stop={"not": "a stop sequence"})

    assert call_args == {"temperature": 0.5}


def test_completion_call_args_drop_malformed_logit_bias():
    call_args = _completion_call_args(logit_bias={"not-a-token-id": 5}, seed=3)

    assert "logit_bias" not in call_args
    assert call_args == {"temperature": 0.5, "seed": 3}
