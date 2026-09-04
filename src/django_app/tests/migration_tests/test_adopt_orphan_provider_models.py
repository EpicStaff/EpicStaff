import importlib

import pytest
from django.apps import apps as global_apps
from django.db import connection

from tables.models import Provider
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.llm_models import (
    LLMConfig,
    LLMModel,
    RealtimeConfig,
    RealtimeModel,
)
from tables.models.rbac_models import Organization

# A module whose name starts with a digit is not a valid identifier, so a plain
# `from ... import` is a SyntaxError — importlib handles it fine.
_migration = importlib.import_module(
    "tables.migrations.0235_adopt_orphan_provider_models"
)
adopt_orphans = _migration.adopt_orphans
collapse_duplicates = _migration.collapse_duplicates


@pytest.fixture
def orgs(db):
    return (
        Organization.objects.create(name="Org A"),
        Organization.objects.create(name="Org B"),
    )


@pytest.fixture
def provider(db):
    return Provider.objects.create(name="prov")


def _adopt_llm():
    adopt_orphans(
        global_apps,
        model_label="tables.LLMModel",
        config_label="tables.LLMConfig",
        config_fk="model",
    )


@pytest.mark.django_db
def test_row_referenced_by_one_org_is_adopted(orgs, provider):
    org_a, _org_b = orgs
    orphan = LLMModel.objects.create(
        name="quickstart-minted",
        llm_provider=provider,
        is_custom=False,
        predefined=False,
    )
    LLMConfig.objects.create(custom_name="qs", model=orphan, org=org_a)

    _adopt_llm()

    orphan.refresh_from_db()
    assert orphan.org_id == org_a.id
    assert orphan.is_custom is True


@pytest.mark.django_db
def test_row_referenced_by_two_orgs_is_left_shared(orgs, provider):
    org_a, org_b = orgs
    orphan = LLMModel.objects.create(
        name="contested", llm_provider=provider, is_custom=False, predefined=False
    )
    LLMConfig.objects.create(custom_name="a", model=orphan, org=org_a)
    LLMConfig.objects.create(custom_name="b", model=orphan, org=org_b)

    _adopt_llm()

    orphan.refresh_from_db()
    assert orphan.org_id is None
    assert orphan.is_custom is False


@pytest.mark.django_db
def test_unreferenced_row_is_left_shared(orgs, provider):
    orphan = LLMModel.objects.create(
        name="unused", llm_provider=provider, is_custom=False, predefined=False
    )

    _adopt_llm()

    orphan.refresh_from_db()
    assert orphan.org_id is None
    assert orphan.is_custom is False


@pytest.mark.django_db
def test_genuine_builtin_is_never_touched(orgs, provider):
    """predefined=True marks a catalog row seeded by upload_models; it must stay shared
    even when only one org references it."""
    org_a, _org_b = orgs
    builtin = LLMModel.objects.create(
        name="gpt-4o", llm_provider=provider, is_custom=False, predefined=True
    )
    LLMConfig.objects.create(custom_name="uses-builtin", model=builtin, org=org_a)

    _adopt_llm()

    builtin.refresh_from_db()
    assert builtin.org_id is None
    assert builtin.is_custom is False


@pytest.mark.django_db
def test_nothing_is_deleted(orgs, provider):
    """LLMConfig.model is CASCADE — an adoption that deleted rows would destroy
    live configs in multiple orgs."""
    org_a, org_b = orgs
    contested = LLMModel.objects.create(
        name="contested", llm_provider=provider, is_custom=False, predefined=False
    )
    LLMConfig.objects.create(custom_name="a", model=contested, org=org_a)
    LLMConfig.objects.create(custom_name="b", model=contested, org=org_b)

    _adopt_llm()

    assert LLMModel.objects.filter(id=contested.id).exists()
    assert LLMConfig.objects.count() == 2


@pytest.mark.django_db
def test_embedding_models_are_adopted_too(orgs, provider):
    org_a, _org_b = orgs
    orphan = EmbeddingModel.objects.create(
        name="qs-emb",
        embedding_provider=provider,
        is_custom=False,
        predefined=False,
    )
    EmbeddingConfig.objects.create(custom_name="qs", model=orphan, org=org_a)

    adopt_orphans(
        global_apps,
        model_label="tables.EmbeddingModel",
        config_label="tables.EmbeddingConfig",
        config_fk="model",
    )

    orphan.refresh_from_db()
    assert orphan.org_id == org_a.id
    assert orphan.is_custom is True


# ---- same-org duplicate collapse (0236 would otherwise fail its constraint) ----


def _collapse_realtime():
    collapse_duplicates(
        global_apps,
        model_label="tables.RealtimeModel",
        config_label="tables.RealtimeConfig",
        config_fk="realtime_model",
    )


@pytest.fixture
def without_realtime_per_org_constraint(db):
    """Drops the constraint 0236 adds, so the pre-0236 duplicate state this
    function exists to clean up can be constructed at all.

    Postgres DDL is transactional and pytest-django rolls each test back, so the
    constraint is restored automatically.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE tables_realtimemodel "
            "DROP CONSTRAINT unique_realtimemodel_name_provider_per_org"
        )
    yield


@pytest.mark.django_db
def test_same_org_duplicates_collapse_onto_the_lowest_pk(
    orgs, provider, without_realtime_per_org_constraint
):
    org_a, _org_b = orgs
    first = RealtimeModel.objects.create(
        name="dup", provider=provider, org=org_a, is_custom=True
    )
    second = RealtimeModel.objects.create(
        name="dup", provider=provider, org=org_a, is_custom=True
    )

    _collapse_realtime()

    assert RealtimeModel.objects.filter(id=first.id).exists()
    assert not RealtimeModel.objects.filter(id=second.id).exists()


@pytest.mark.django_db
def test_collapse_repoints_configs_instead_of_cascading_them_away(
    orgs, provider, without_realtime_per_org_constraint
):
    """RealtimeConfig.realtime_model is CASCADE, so deleting the duplicate before
    re-pointing would destroy that org's live config."""
    org_a, _org_b = orgs
    keeper = RealtimeModel.objects.create(
        name="dup", provider=provider, org=org_a, is_custom=True
    )
    extra = RealtimeModel.objects.create(
        name="dup", provider=provider, org=org_a, is_custom=True
    )
    config = RealtimeConfig.objects.create(
        custom_name="cfg", realtime_model=extra, org=org_a
    )

    _collapse_realtime()

    config.refresh_from_db()
    assert config.realtime_model_id == keeper.id


@pytest.mark.django_db
def test_collapse_leaves_a_builtin_and_its_org_override_alone(orgs, provider):
    """Different org (NULL vs A) means both satisfy the new per-org constraint."""
    org_a, _org_b = orgs
    builtin = RealtimeModel.objects.create(
        name="shadowed", provider=provider, org=None, is_custom=False
    )
    override = RealtimeModel.objects.create(
        name="shadowed", provider=provider, org=org_a, is_custom=True
    )

    _collapse_realtime()

    assert RealtimeModel.objects.filter(id=builtin.id).exists()
    assert RealtimeModel.objects.filter(id=override.id).exists()


@pytest.mark.django_db
def test_collapse_handles_a_three_way_duplicate(
    orgs, provider, without_realtime_per_org_constraint
):
    org_a, _org_b = orgs
    rows = [
        RealtimeModel.objects.create(
            name="tri", provider=provider, org=org_a, is_custom=True
        )
        for _ in range(3)
    ]
    for row in rows[1:]:
        RealtimeConfig.objects.create(
            custom_name=f"cfg-{row.id}", realtime_model=row, org=org_a
        )

    _collapse_realtime()

    surviving = RealtimeModel.objects.filter(name="tri", org=org_a)
    assert surviving.count() == 1
    assert surviving.first().id == rows[0].id
    assert RealtimeConfig.objects.filter(realtime_model_id=rows[0].id).count() == 2
