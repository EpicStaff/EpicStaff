"""A config switching models and a rename of a model cannot both pass on stale reads.

LiteLLM routes a config's requests by its model's name, so a rename can move them. Two
concurrent requests could each pass their own check: a secret-bearing config switching to
a model whose name reads harmless, while that model is renamed to route elsewhere and no
secret-bearing config of it exists yet. Both checks lock the model row
(`select_for_update`) and read it after the lock, and the viewset runs the check and the
save in one transaction (`SecretUseCheckedViewSetMixin.secret_use_check_locks_rows`), so
whichever request runs second sees what the first committed; without the flag the mixin
opens no transaction. Quickstart, which attaches its new secret to a model it resolves by
name, locks an organization's own row the same way, and so does a config naming its model
by provider and model name when a concurrent request added that row after it was resolved.

These tests pin the pieces that make that hold: which queries lock, in what order, that
the values come from the locked row, and that the lock lives as long as the save. A
two-thread race test is deliberately not written: its outcome depends on scheduling, so
it would be flaky. pytest-django runs every test inside a transaction, which is what lets
`select_for_update` run here outside a viewset, and the savepoints opened inside it are
what tell a mixin transaction from none.
"""

import pytest
from ai_models.domain.specs import ModelKind
from ai_models.models import EmbeddingConfig, EmbeddingModel, LLMConfig, LLMModel, Provider
from ai_models.services.catalog_model_resolver import CatalogModelResolver
from ai_models.views.model_view_sets import (
    EmbeddingConfigReadWriteViewSet,
    EmbeddingModelReadWriteViewSet,
    LLMConfigReadWriteViewSet,
    LLMModelReadWriteViewSet,
)
from django.db import connection
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext
from rest_framework import mixins
from tables.models import Secret
from tables.services.quickstart_service import QuickstartService
from tables.services.secrets import SecretUseDeniedError, secret_service
from tables.services.secrets.secret_use_checks import (
    check_embedding_config_write,
    check_embedding_model_write,
    check_llm_config_write,
    check_llm_model_write,
)
from tables.views.secret_use import SecretUseCheckedViewSetMixin

from tests.custom_role_fixtures import *
from tests.rbac_cross_org_fixtures import *

ROUTING_NAME = "huggingface/https://attacker.example.com/v1"

CONFIG_KINDS = [
    pytest.param(LLMModel, "llm_provider", LLMConfig, check_llm_config_write, id="llm"),
    pytest.param(
        EmbeddingModel,
        "embedding_provider",
        EmbeddingConfig,
        check_embedding_config_write,
        id="embedding",
    ),
]
MODEL_ROW_KINDS = [
    pytest.param(LLMModel, "llm_provider", LLMConfig, check_llm_model_write, id="llm"),
    pytest.param(
        EmbeddingModel,
        "embedding_provider",
        EmbeddingConfig,
        check_embedding_model_write,
        id="embedding",
    ),
]


@pytest.fixture
def secret(default_org) -> Secret:
    return secret_service.create(text="sk-locking", org=default_org, name="LOCKING_SECRET")


@pytest.fixture
def make_model(default_org, openai_provider):
    def _make(model_class, provider_field, name):
        return model_class.objects.create(
            name=name, is_custom=True, org=default_org, **{provider_field: openai_provider}
        )

    return _make


@pytest.fixture
def make_config(default_org):
    def _make(config_class, model, secret=None):
        return config_class.objects.create(
            custom_name="locking-config", model=model, api_key_secret=secret, org=default_org
        )

    return _make


def _locking_query_indexes(captured: CaptureQueriesContext, table: str) -> list[int]:
    return [
        index
        for index, query in enumerate(captured.captured_queries)
        if "FOR NO KEY UPDATE" in query["sql"] and f'FROM "{table}"' in query["sql"]
    ]


def _query_indexes_reading(captured: CaptureQueriesContext, table: str) -> list[int]:
    return [
        index
        for index, query in enumerate(captured.captured_queries)
        if f'FROM "{table}"' in query["sql"]
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("carries_secret", [True, False], ids=["secret", "no-secret"])
@pytest.mark.parametrize("model_class, provider_field, config_class, config_check", CONFIG_KINDS)
def test_model_switch_locks_the_incoming_model_row(
    make_model, make_config, secret, model_class, provider_field, config_class, config_check,
    carries_secret,
):
    # Without a secret too: every switch takes the model locks before it updates the
    # config row, so two switches never take them in opposite orders and deadlock.
    current_model = make_model(model_class, provider_field, "current")
    incoming_model = make_model(model_class, provider_field, "incoming")
    config = make_config(config_class, current_model, secret if carries_secret else None)

    with CaptureQueriesContext(connection) as captured:
        config_check(None, config, {"model": incoming_model})

    assert _locking_query_indexes(captured, model_class._meta.db_table)


@pytest.mark.django_db
@pytest.mark.parametrize("model_class, provider_field, config_class, config_check", CONFIG_KINDS)
def test_model_switch_reads_the_name_from_the_locked_row(
    make_model, make_config, secret, model_class, provider_field, config_class, config_check
):
    current_model = make_model(model_class, provider_field, "current")
    incoming_model = make_model(model_class, provider_field, "incoming")
    config = make_config(config_class, current_model, secret)
    # The object validated with the request still has its harmless name, while a
    # concurrent request has already committed the routing name to its row.
    stale_incoming_model = model_class.objects.get(pk=incoming_model.pk)
    model_class.objects.filter(pk=incoming_model.pk).update(name=ROUTING_NAME)

    with pytest.raises(SecretUseDeniedError) as denied:
        config_check(None, config, {"model": stale_incoming_model})

    assert denied.value.field_path == ("model",)


@pytest.mark.django_db
@pytest.mark.parametrize("model_class, provider_field, config_class, config_check", CONFIG_KINDS)
def test_model_switch_between_built_in_models_locks_no_row_yet_reads_their_names(
    make_config, secret, openai_provider, model_class, provider_field, config_class, config_check
):
    # A built-in row is shared by every organization and cannot be renamed: locking it
    # would hold up every other organization's config writes on it.
    current_model, incoming_model = (
        model_class.objects.create(name=name, org=None, **{provider_field: openai_provider})
        for name in ("built-in-current", ROUTING_NAME)
    )
    config = make_config(config_class, current_model, secret)

    with CaptureQueriesContext(connection) as captured, pytest.raises(SecretUseDeniedError):
        config_check(None, config, {"model": incoming_model})

    assert _locking_query_indexes(captured, model_class._meta.db_table) == []


@pytest.mark.django_db
@pytest.mark.parametrize("model_class, provider_field, config_class, model_check", MODEL_ROW_KINDS)
def test_model_rename_locks_the_model_row_before_counting_configs(
    make_model, make_config, secret, model_class, provider_field, config_class, model_check
):
    model = make_model(model_class, provider_field, "renamed")
    make_config(config_class, model, secret)

    with CaptureQueriesContext(connection) as captured:
        with pytest.raises(SecretUseDeniedError):
            model_check(None, model, {"name": ROUTING_NAME})

    lock_indexes = _locking_query_indexes(captured, model_class._meta.db_table)
    config_query_indexes = _query_indexes_reading(captured, config_class._meta.db_table)
    assert lock_indexes
    assert config_query_indexes
    assert lock_indexes[0] < config_query_indexes[0]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "data", [{"name": "harmless"}, {"is_visible": False}], ids=["name-resent", "name-not-sent"]
)
@pytest.mark.parametrize("model_class, provider_field, config_class, model_check", MODEL_ROW_KINDS)
def test_stale_model_write_reverting_a_concurrent_rename_is_checked(
    make_model, make_config, secret, model_class, provider_field, config_class, model_check, data
):
    model = make_model(model_class, provider_field, "harmless")
    make_config(config_class, model, secret)
    # The row read with the request still has the old name, which its save writes back,
    # while a concurrent request has already committed the routing name.
    stale_model = model_class.objects.get(pk=model.pk)
    model_class.objects.filter(pk=model.pk).update(name=ROUTING_NAME)

    with pytest.raises(SecretUseDeniedError) as denied:
        model_check(None, stale_model, data)

    assert denied.value.field_path == ("name",)


@pytest.mark.django_db
@pytest.mark.parametrize("data", [{}, "same-model"], ids=["model-not-sent", "same-model"])
@pytest.mark.parametrize("model_class, provider_field, config_class, config_check", CONFIG_KINDS)
def test_no_lock_when_the_config_keeps_its_model(
    make_model, make_config, secret, model_class, provider_field, config_class, config_check, data
):
    model = make_model(model_class, provider_field, "kept")
    config = make_config(config_class, model, secret)

    with CaptureQueriesContext(connection) as captured:
        config_check(None, config, {"model": model} if data == "same-model" else data)

    assert _locking_query_indexes(captured, model_class._meta.db_table) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kind, model_class, provider_field",
    [
        pytest.param(ModelKind.LLM, LLMModel, "llm_provider", id="llm"),
        pytest.param(ModelKind.EMBEDDING, EmbeddingModel, "embedding_provider", id="embedding"),
    ],
)
def test_quickstart_locks_the_organizations_own_model_row(
    make_model, default_org, kind, model_class, provider_field
):
    own_model = make_model(model_class, provider_field, _quickstart_model_name(kind))

    with CaptureQueriesContext(connection) as captured:
        model = QuickstartService()._model(kind, provider="openai", org_id=default_org.pk, author=None)

    assert model.pk == own_model.pk
    assert _locking_query_indexes(captured, model_class._meta.db_table)


@pytest.mark.django_db
def test_quickstart_resolves_again_when_its_row_was_renamed_before_the_lock(
    make_model, default_org, monkeypatch
):
    name = _quickstart_model_name(ModelKind.LLM)
    own_model = make_model(LLMModel, "llm_provider", name)
    resolve = CatalogModelResolver.resolve

    def resolve_then_rename(self, *args, **kwargs):
        # A rename commits between the resolve and the lock, once.
        resolved = resolve(self, *args, **kwargs)
        LLMModel.objects.filter(pk=own_model.pk, name=name).update(name=ROUTING_NAME)
        return resolved

    monkeypatch.setattr(CatalogModelResolver, "resolve", resolve_then_rename)

    model = QuickstartService()._model(
        ModelKind.LLM, provider="openai", org_id=default_org.pk, author=None
    )

    assert model.pk != own_model.pk
    assert model.name == name


CONFIG_ENDPOINTS = [
    pytest.param("/api/llm-configs/", LLMModel, "llm_provider", LLMConfig, id="llm"),
    pytest.param(
        "/api/embedding-configs/",
        EmbeddingModel,
        "embedding_provider",
        EmbeddingConfig,
        id="embedding",
    ),
]
CUSTOM_MODEL_NAME = "my-custom-model"


@pytest.fixture
def acme_client(org_client_as, admin_acme, acme):
    return org_client_as(admin_acme, acme)


def _add_row_after_resolving(monkeypatch, model_class, provider_field, org):
    """Make a concurrent request add the org's row of the name once `resolve` has found none."""
    resolve = CatalogModelResolver.resolve
    added = {}

    def resolve_then_add(self, *args, **kwargs):
        resolved = resolve(self, *args, **kwargs)
        added["row"] = model_class.objects.create(
            name=resolved.name,
            org=org,
            is_custom=True,
            **{provider_field: getattr(resolved, provider_field)},
        )
        return resolved

    monkeypatch.setattr(CatalogModelResolver, "resolve", resolve_then_add)
    return added


@pytest.mark.django_db
@pytest.mark.parametrize("path, model_class, provider_field, config_class", CONFIG_ENDPOINTS)
def test_config_write_by_name_locks_the_row_a_concurrent_request_added(
    acme_client, acme, monkeypatch, path, model_class, provider_field, config_class
):
    Provider.objects.get_or_create(name="openai")
    added = _add_row_after_resolving(monkeypatch, model_class, provider_field, acme)

    with CaptureQueriesContext(connection) as captured:
        response = acme_client.post(
            path,
            {"custom_name": "config", "provider": "openai", "model_name": CUSTOM_MODEL_NAME},
            format="json",
        )

    assert response.status_code == 201, response.data
    assert config_class.objects.get(pk=response.data["id"]).model_id == added["row"].pk
    # A rename of that row locks it too, so it waits until the config is stored.
    assert _locking_query_indexes(captured, model_class._meta.db_table)


@pytest.mark.django_db
@pytest.mark.parametrize("path, model_class, provider_field, config_class", CONFIG_ENDPOINTS)
def test_config_write_by_name_gets_a_new_row_when_the_added_row_was_renamed_before_the_lock(
    acme_client, acme, monkeypatch, path, model_class, provider_field, config_class
):
    Provider.objects.get_or_create(name="openai")
    added = _add_row_after_resolving(monkeypatch, model_class, provider_field, acme)
    get_or_create = QuerySet.get_or_create

    def get_or_create_then_rename(self, *args, **kwargs):
        # A rename commits between `get_or_create` finding the row and the lock, once.
        row, created = get_or_create(self, *args, **kwargs)
        if self.model is model_class and not created and row.name == CUSTOM_MODEL_NAME:
            model_class.objects.filter(pk=row.pk).update(name=ROUTING_NAME)
        return row, created

    monkeypatch.setattr(QuerySet, "get_or_create", get_or_create_then_rename)

    response = acme_client.post(
        path,
        {"custom_name": "config", "provider": "openai", "model_name": CUSTOM_MODEL_NAME},
        format="json",
    )

    assert response.status_code == 201, response.data
    model = config_class.objects.get(pk=response.data["id"]).model
    assert model.pk != added["row"].pk
    assert (model.name, model.org_id) == (CUSTOM_MODEL_NAME, acme.pk)
    assert model_class.objects.get(pk=added["row"].pk).name == ROUTING_NAME


def _quickstart_model_name(kind) -> str:
    model_key = "llm_model" if kind == ModelKind.LLM else "embedding_model"
    return QuickstartService.PROVIDER_CONFIGS["openai"][model_key]


class _RecordingSerializer:
    """Stands in for a validated serializer; records the open savepoints when saved."""

    def __init__(self, log: list):
        self._log = log
        self.instance = None
        self.validated_data = {}

    def save(self, **kwargs):
        self._log.append(("save", list(connection.savepoint_ids)))


def _viewset(log: list, *, locks_rows: bool):
    def check(actor, instance, data):
        log.append(("check", list(connection.savepoint_ids)))

    viewset_class = type(
        "_ViewSet",
        (SecretUseCheckedViewSetMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin),
        {"secret_use_check": check, "secret_use_check_locks_rows": locks_rows},
    )
    viewset = viewset_class()
    viewset.request = None
    return viewset


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["create", "update"])
def test_mixin_runs_check_and_save_in_one_atomic_block(action):
    log = []
    savepoints_before = list(connection.savepoint_ids)

    getattr(_viewset(log, locks_rows=True), f"perform_{action}")(_RecordingSerializer(log))

    (check_step, check_savepoints), (save_step, save_savepoints) = log
    assert (check_step, save_step) == ("check", "save")
    # One savepoint opened for the write, and the same one still open at the save.
    assert len(check_savepoints) == len(savepoints_before) + 1
    assert save_savepoints == check_savepoints
    assert list(connection.savepoint_ids) == savepoints_before


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["create", "update"])
def test_mixin_without_row_locks_opens_no_transaction(action):
    # A save with side effects outside the database (a TelegramTriggerNode's post_save
    # calls the Telegram API) must not run inside a transaction the mixin opened.
    log = []
    savepoints_before = list(connection.savepoint_ids)

    getattr(_viewset(log, locks_rows=False), f"perform_{action}")(_RecordingSerializer(log))

    assert log == [("check", savepoints_before), ("save", savepoints_before)]


# Every test runs inside a transaction, so a viewset that forgot the flag would still
# pass the tests above, yet in production its lock would end with the check, before
# the save (or select_for_update would fail outside a transaction).
@pytest.mark.parametrize(
    "viewset_class",
    [
        LLMConfigReadWriteViewSet,
        EmbeddingConfigReadWriteViewSet,
        LLMModelReadWriteViewSet,
        EmbeddingModelReadWriteViewSet,
    ],
)
def test_viewsets_whose_check_locks_the_model_hold_the_lock_through_the_save(viewset_class):
    assert viewset_class.secret_use_check_locks_rows is True
