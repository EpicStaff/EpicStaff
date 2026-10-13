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
    *, rag_id: int = 1, slot: SlotEnum = SlotEnum.A
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
        temperature=0.5,
        max_tokens=None,
        top_p=None,
        api_key="sk-test",
        model=llm_model,
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
