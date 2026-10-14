import types

import pytest

pytest.importorskip(
    "psycopg",
    reason="requires libpq; only available in the Linux/Docker image, not this Windows venv",
    exc_type=ImportError,  # psycopg is installed but fails at import time without libpq
)

from domain.enums import SlotEnum  # noqa: E402
from infrastructure.database.mappers.graph import graph_rag_orm_to_graphrag_config  # noqa: E402


def _make_fake_rag(
    *, rag_id: int = 1, slot: SlotEnum = SlotEnum.A, **llm_config_fields
) -> types.SimpleNamespace:
    """Build a minimal fake GraphRag ORM row with the fields _to_graph_rag_config reads."""
    provider = types.SimpleNamespace(name="openai")
    llm_model = types.SimpleNamespace(
        name="gpt-4o",
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
        index_config=index_config,
    )


def test_to_graph_rag_config_populates_vector_store_index_schema():
    rag = _make_fake_rag(slot=SlotEnum.A)

    config = graph_rag_orm_to_graphrag_config(rag, slot=SlotEnum.A)

    assert (
        config.vector_store.index_schema
    ), "vector_store.index_schema must be non-empty — the @model_validator did not run"
    assert (
        "entity_description" in config.vector_store.index_schema
    ), "KeyError regression: 'entity_description' must be present in index_schema"


def test_to_graph_rag_config_uses_requested_slot_not_row_slot():
    rag = _make_fake_rag(rag_id=7, slot=SlotEnum.A)

    config = graph_rag_orm_to_graphrag_config(rag, slot=SlotEnum.B)

    assert (
        "/b/output" in config.output_storage.prefix
    ), f"output_storage.prefix should contain '/b/output', got: {config.output_storage.prefix!r}"
    assert (
        "/b/lancedb" in config.vector_store.db_uri
    ), f"vector_store.db_uri should contain '/b/lancedb', got: {config.vector_store.db_uri!r}"
    assert (
        "/a/" not in config.output_storage.prefix
    ), "output_storage.prefix must not use the row's active slot (A) when slot=B was requested"


@pytest.mark.parametrize(
    "slot, expected_output_subdir, expected_lancedb_subdir",
    [
        (SlotEnum.A, "/a/output", "/a/lancedb"),
        (SlotEnum.B, "/b/output", "/b/lancedb"),
    ],
    ids=["slot_a", "slot_b"],
)
def test_to_graph_rag_config_slot_routing(
    slot, expected_output_subdir, expected_lancedb_subdir
):
    rag = _make_fake_rag(rag_id=42, slot=SlotEnum.A)
    config = graph_rag_orm_to_graphrag_config(rag, slot=slot)

    assert expected_output_subdir in config.output_storage.prefix
    assert expected_lancedb_subdir in config.vector_store.db_uri
    assert "entity_description" in config.vector_store.index_schema


def _completion_call_args(**llm_config_fields) -> dict:
    rag = _make_fake_rag(**llm_config_fields)
    config = graph_rag_orm_to_graphrag_config(rag, slot=SlotEnum.A)
    return config.completion_models["default_completion_model"].call_args


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
