"""A config switching models and an edit of a model's `base_url` cannot both pass on stale reads.

Two concurrent requests could each pass their own check: a secret-bearing config
switching to a model whose `base_url` reads empty, while that model's `base_url` is
pointed elsewhere and no secret-bearing config of it exists yet. Both checks lock the
model row (`select_for_update`) and read it after the lock, and the viewset runs the
check and the save in one transaction, so whichever request runs second sees what the
first committed.

These tests pin the pieces that make that hold: which queries lock, in what order,
that the values come from the locked row, and that the lock lives as long as the
save. A two-thread race test is deliberately not written: its outcome depends on
scheduling, so it would be flaky. pytest-django runs every test inside a transaction,
which is what lets `select_for_update` run here outside a viewset.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import mixins
from tables.models import Secret
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.llm_models import LLMConfig, LLMModel
from tables.services.secrets import SecretUseDeniedError, secret_service
from tables.services.secrets.secret_use_checks import (
    check_embedding_config_write,
    check_embedding_model_write,
    check_llm_config_write,
    check_llm_model_write,
)
from tables.views.model_view_sets import (
    EmbeddingConfigReadWriteViewSet,
    EmbeddingModelReadWriteViewSet,
    LLMConfigReadWriteViewSet,
    LLMModelReadWriteViewSet,
)
from tables.views.secret_use import SecretUseCheckedViewSetMixin

ATTACKER_URL = "https://attacker.example.com/v1"

MODEL_KINDS = [
    pytest.param(
        LLMModel, "llm_provider", LLMConfig, check_llm_config_write, check_llm_model_write, id="llm"
    ),
    pytest.param(
        EmbeddingModel,
        "embedding_provider",
        EmbeddingConfig,
        check_embedding_config_write,
        check_embedding_model_write,
        id="embedding",
    ),
]


@pytest.fixture
def secret(default_org) -> Secret:
    return secret_service.create(text="sk-locking", org=default_org, name="LOCKING_SECRET")


@pytest.fixture
def make_model(default_org, openai_provider):
    def _make(model_class, provider_field, name, base_url=None):
        return model_class.objects.create(
            name=name,
            base_url=base_url,
            is_custom=True,
            org=default_org,
            **{provider_field: openai_provider},
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
        if "FOR UPDATE" in query["sql"] and f'FROM "{table}"' in query["sql"]
    ]


def _query_indexes_reading(captured: CaptureQueriesContext, table: str) -> list[int]:
    return [
        index
        for index, query in enumerate(captured.captured_queries)
        if f'FROM "{table}"' in query["sql"]
    ]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model_class, provider_field, config_class, config_check, model_check", MODEL_KINDS
)
def test_model_switch_locks_the_incoming_model_row(
    make_model, make_config, secret, model_class, provider_field, config_class, config_check,
    model_check,
):
    current_model = make_model(model_class, provider_field, "current")
    incoming_model = make_model(model_class, provider_field, "incoming")
    config = make_config(config_class, current_model, secret)

    with CaptureQueriesContext(connection) as captured:
        config_check(None, config, {"model": incoming_model})

    assert _locking_query_indexes(captured, model_class._meta.db_table)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model_class, provider_field, config_class, config_check, model_check", MODEL_KINDS
)
def test_model_switch_reads_base_url_from_the_locked_row(
    make_model, make_config, secret, model_class, provider_field, config_class, config_check,
    model_check,
):
    current_model = make_model(model_class, provider_field, "current")
    incoming_model = make_model(model_class, provider_field, "incoming")
    config = make_config(config_class, current_model, secret)
    # The object validated with the request still has no base_url, while a concurrent
    # request has already committed the attacker's URL to its row.
    stale_incoming_model = model_class.objects.get(pk=incoming_model.pk)
    model_class.objects.filter(pk=incoming_model.pk).update(base_url=ATTACKER_URL)

    with pytest.raises(SecretUseDeniedError) as denied:
        config_check(None, config, {"model": stale_incoming_model})

    assert denied.value.field_path == ("model",)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model_class, provider_field, config_class, config_check, model_check", MODEL_KINDS
)
def test_model_base_url_edit_locks_the_model_row_before_counting_configs(
    make_model, make_config, secret, model_class, provider_field, config_class, config_check,
    model_check,
):
    model = make_model(model_class, provider_field, "edited")
    make_config(config_class, model, secret)

    with CaptureQueriesContext(connection) as captured:
        with pytest.raises(SecretUseDeniedError):
            model_check(None, model, {"base_url": ATTACKER_URL})

    lock_indexes = _locking_query_indexes(captured, model_class._meta.db_table)
    config_query_indexes = _query_indexes_reading(captured, config_class._meta.db_table)
    assert lock_indexes
    assert config_query_indexes
    assert lock_indexes[0] < config_query_indexes[0]


@pytest.mark.django_db
@pytest.mark.parametrize("write", ["no_secret_switches_model", "secret_keeps_model"])
@pytest.mark.parametrize(
    "model_class, provider_field, config_class, config_check, model_check", MODEL_KINDS
)
def test_no_lock_when_config_carries_no_secret_or_keeps_its_model(
    make_model, make_config, secret, model_class, provider_field, config_class, config_check,
    model_check, write,
):
    current_model = make_model(model_class, provider_field, "current")
    other_model = make_model(model_class, provider_field, "other", base_url=ATTACKER_URL)
    if write == "no_secret_switches_model":
        config = make_config(config_class, current_model)
        data = {"model": other_model}
    else:
        config = make_config(config_class, current_model, secret)
        data = {"model": current_model}

    with CaptureQueriesContext(connection) as captured:
        config_check(None, config, data)

    assert captured.captured_queries == []


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
