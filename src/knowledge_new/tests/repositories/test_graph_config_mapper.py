import functools
import logging
import types

import pytest

pytest.importorskip(
    "psycopg",
    reason="requires libpq; only available in the Linux/Docker image, not this Windows venv",
    exc_type=ImportError,  # psycopg is installed but fails at import time without libpq
)

from domain.enums import SlotEnum  # noqa: E402
from graphrag.logger.standard_logging import init_loggers  # noqa: E402
from graphrag_llm.config import ModelConfig, RetryConfig  # noqa: E402
from infrastructure.database.mappers import graph as graph_mapper  # noqa: E402
from infrastructure.database.mappers.graph import (  # noqa: E402
    graph_rag_cache_config,
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
) -> types.SimpleNamespace:
    """Build a minimal fake GraphRag ORM row with the fields _to_graph_rag_config reads."""
    provider = types.SimpleNamespace(name=provider_name)
    llm_model = types.SimpleNamespace(name=model_name, llm_provider=provider)
    llm_config = types.SimpleNamespace(
        id=1,
        input_cost_per_token=0.000002,
        output_cost_per_token=0.00001,
        model=llm_model,
    )

    embedding_provider = types.SimpleNamespace(name="openai")
    embedding_model = types.SimpleNamespace(
        name="text-embedding-ada-002",
        embedding_provider=embedding_provider,
    )
    embedding_config = types.SimpleNamespace(model=embedding_model)

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


def _completion_model(**rag_fields):
    rag = _make_fake_rag(**rag_fields)
    config = graph_rag_orm_to_graphrag_config(rag, slot=SlotEnum.A)
    return config.completion_models["default_completion_model"]


def test_settings_never_come_from_the_database_row():
    """django_app sends the settings the model catalog allows with each request."""
    config = graph_rag_orm_to_graphrag_config(_make_fake_rag(), slot=SlotEnum.A)

    assert config.completion_models["default_completion_model"].call_args == {}
    assert config.embedding_models["default_embedding_model"].call_args == {}


def test_an_azure_llm_maps_before_the_request_supplies_its_endpoint():
    """The endpoint, key and deployment arrive with each request (apply_request_access);
    loading the config, as metrics does, must not need them."""
    completion_model = _completion_model(provider_name="azure", model_name="gpt-4o")

    assert completion_model.model_provider == "azure"
    assert completion_model.model == "gpt-4o"


def test_cache_lives_in_object_storage_of_this_rag_and_is_shared_by_both_slots():
    # A reindex into the other slot must find the answers the first slot cached.
    rag = _make_fake_rag(rag_id=42)

    slot_a = graph_rag_orm_to_graphrag_config(rag, slot=SlotEnum.A)
    slot_b = graph_rag_orm_to_graphrag_config(rag, slot=SlotEnum.B)

    assert slot_a.cache.type == "json"
    assert slot_a.cache.storage.type == "s3"
    assert slot_a.cache.storage.prefix.startswith("graphrag/rag_42/cache/")
    assert slot_b.cache.storage.prefix == slot_a.cache.storage.prefix


def _change_llm_model(rag):
    rag.llm.model.name = "gpt-4o-mini"


def _change_embedding_model(rag):
    rag.embedder.model.name = "text-embedding-3-large"


@pytest.mark.parametrize(
    "change",
    [_change_llm_model, _change_embedding_model],
    ids=["llm_model", "embedding_model"],
)
def test_changing_a_model_setting_starts_a_new_cache(change):
    # graphrag's cache key is the prompt alone, so a new model must not get old answers.
    rag = _make_fake_rag(rag_id=42)
    before = graph_rag_orm_to_graphrag_config(rag, slot=SlotEnum.A).cache.storage.prefix

    change(rag)
    after = graph_rag_orm_to_graphrag_config(rag, slot=SlotEnum.A).cache.storage.prefix

    assert after != before
    assert after.startswith("graphrag/rag_42/cache/")


def _cache_prefix(completion_settings: dict, completion_call_args: dict | None = None) -> str:
    completion_model = _completion_model()
    if completion_call_args is not None:
        completion_model.call_args = completion_call_args
    embedding_model = graph_rag_orm_to_graphrag_config(
        _make_fake_rag(), slot=SlotEnum.A
    ).embedding_models["default_embedding_model"]
    return graph_rag_cache_config(
        42, [(completion_model, completion_settings), (embedding_model, {})]
    ).storage.prefix


def test_changing_a_setting_a_request_runs_the_model_with_starts_a_new_cache():
    # Settings arrive with each request, so the orchestrators name the cache by them.
    before = _cache_prefix({"temperature": 0.5})

    after = _cache_prefix({"temperature": 0.9})

    assert after != before
    assert after.startswith("graphrag/rag_42/cache/")


def test_secrets_and_headers_a_request_adds_keep_the_cache():
    # A key rotation must not throw the cached answers away.
    before = _cache_prefix({"temperature": 0.5}, {"aws_secret_access_key": "old-key"})

    after = _cache_prefix(
        {"temperature": 0.5},
        {"aws_secret_access_key": "new-key", "extra_headers": {"Authorization": "Bearer new"}},
    )

    assert after == before


def test_a_graphrag_default_that_changes_no_answer_keeps_the_cache(monkeypatch):
    rag = _make_fake_rag(rag_id=42)
    before = graph_rag_orm_to_graphrag_config(rag, slot=SlotEnum.A).cache.storage.prefix

    # Stands in for a graphrag upgrade that changes the retry and metrics defaults.
    upgraded_model_config = functools.partial(
        ModelConfig, retry=RetryConfig(max_retries=7), metrics=None
    )
    monkeypatch.setattr(graph_mapper, "ModelConfig", upgraded_model_config)
    after = graph_rag_orm_to_graphrag_config(rag, slot=SlotEnum.A).cache.storage.prefix

    assert after == before


def test_graphrag_log_reaches_the_root_logger_once_and_writes_no_file(
    tmp_path, monkeypatch, caplog, capsys
):
    # The working directory is read-only; graphrag's log must go to the container log only.
    monkeypatch.chdir(tmp_path)
    config = graph_rag_orm_to_graphrag_config(_make_fake_rag(), slot=SlotEnum.A)

    with caplog.at_level(logging.INFO):
        for run in ("first", "second"):
            init_loggers(config=config)
            logging.getLogger("graphrag.index").info("%s run", run)

    assert [record.getMessage() for record in caplog.records] == ["first run", "second run"]
    # graphrag's own handler must write nowhere: the root logger already prints the line.
    assert capsys.readouterr().err == ""
    assert list(tmp_path.iterdir()) == []
