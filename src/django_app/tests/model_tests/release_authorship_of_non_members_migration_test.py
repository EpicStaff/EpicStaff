"""The one-time data migration clears authorship recorded for users outside the row's org."""

import importlib
from datetime import UTC, datetime

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from agents.models import AgentDefinition
from rbac.authorship import record_last_edit
from rbac.authorship.registry import author_tracked_models, last_edit_tracked_models
from rbac.models import OrganizationUser, ResourceLastEdit
from tables.models import Graph, GraphVersion, LLMModel
from tables.models.graph_models import AgentNode, GraphNote
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

MIGRATION = ("rbac", "0005_release_authorship_of_non_members")
migration_module = importlib.import_module(f"{MIGRATION[0]}.migrations.{MIGRATION[1]}")

EDITED_AT = datetime(2024, 2, 3, 4, 5, 6, tzinfo=UTC)
CREATED_AT = "2024-01-02T03:04:05+00:00"


def _state_before_migration():
    return MigrationLoader(connection).project_state(MIGRATION, at_end=False)


def _apply_migration() -> None:
    loader = MigrationLoader(connection)
    migration = loader.get_migration(*MIGRATION)
    with connection.schema_editor() as editor:
        migration.apply(loader.project_state(MIGRATION, at_end=False), editor)


def _last_edit_of(instance) -> ResourceLastEdit:
    return ResourceLastEdit.objects.get(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    )


def _snapshot(*, authors: dict[str, int | None], editors: dict[str, int | None]) -> dict:
    return {
        "nodes": [],
        "node_authorship": {
            node_id: {"created_by": user_id, "created_at": CREATED_AT}
            for node_id, user_id in authors.items()
        },
        "node_last_edit": {
            node_id: {"edited_by": user_id, "edited_at": EDITED_AT.isoformat()}
            for node_id, user_id in editors.items()
        },
    }


@pytest.fixture
def outsider(db, django_user_model, beta, role_member):
    """A member of beta only: the departed member, or the ex-superadmin, of acme."""
    user = django_user_model.objects.create_user(
        email="outsider-migration@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_member)
    return user


@pytest.fixture
def acme_flow(acme):
    return Graph.objects.create(name="migration-flow", org=acme)


# ---- which models it covers ----


@pytest.mark.django_db
def test_covers_the_models_of_the_live_authorship_registries_with_the_same_org_lookups():
    """Compared on the models that exist both live and at the migration's state, so a model
    added after this migration (which has no data predating it) does not count."""
    migrated = {
        model._meta.label_lower: org_lookup
        for model, org_lookup in migration_module.author_tracked_models(
            _state_before_migration().apps
        )
    }
    live_authored = {model._meta.label_lower: lookup for model, lookup in author_tracked_models()}
    live_last_edited = {
        model._meta.label_lower: lookup for model, lookup in last_edit_tracked_models()
    }
    in_both = migrated.keys() & live_authored.keys()

    assert migrated.keys() - live_authored.keys() == set()
    assert {label: migrated[label] for label in in_both} == {
        label: live_authored[label] for label in in_both
    }
    for label, lookup in live_last_edited.items():
        if label in migrated:
            assert migrated[label] == lookup, label
    assert {"tables.graph", "tables.agentnode", "agents.agentdefinition"} <= migrated.keys()


# ---- created_by ----


@pytest.mark.django_db
def test_clears_the_author_who_is_not_a_member_of_the_rows_org(acme, acme_flow, outsider):
    flow = Graph.objects.create(name="outsider-flow", org=acme, created_by=outsider)
    node = AgentNode.objects.create(graph=acme_flow, node_name="agent", created_by=outsider)
    agent = AgentDefinition.objects.create(
        org=acme,
        name="outsider-agent",
        instruction_list=[{"name": "Instruction_1.md", "content": "x"}],
        created_by=outsider,
    )
    soft_deleted_flow = Graph.objects.create(
        name="deleted-outsider-flow",
        org=acme,
        created_by=outsider,
        is_soft_deleted=True,
        soft_deleted_at=timezone.now(),
    )

    _apply_migration()

    assert Graph.all_objects.get(pk=flow.pk).created_by_id is None
    assert AgentNode.all_objects.get(pk=node.pk).created_by_id is None
    assert AgentDefinition.objects.get(pk=agent.pk).created_by_id is None
    assert Graph.all_objects.get(pk=soft_deleted_flow.pk).created_by_id is None


@pytest.mark.django_db
def test_keeps_the_author_who_is_a_member_or_a_superadmin(
    acme, beta, acme_flow, member_only, superadmin, outsider
):
    member_flow = Graph.objects.create(name="member-flow", org=acme, created_by=member_only)
    superadmin_flow = Graph.objects.create(name="sa-flow", org=acme, created_by=superadmin)
    outsider_own_org_flow = Graph.objects.create(name="beta-flow", org=beta, created_by=outsider)
    member_node = AgentNode.objects.create(
        graph=acme_flow, node_name="agent", created_by=member_only
    )

    _apply_migration()

    assert Graph.all_objects.get(pk=member_flow.pk).created_by_id == member_only.id
    assert Graph.all_objects.get(pk=superadmin_flow.pk).created_by_id == superadmin.id
    assert Graph.all_objects.get(pk=outsider_own_org_flow.pk).created_by_id == outsider.id
    assert AgentNode.all_objects.get(pk=member_node.pk).created_by_id == member_only.id


@pytest.mark.django_db
def test_keeps_the_author_of_a_row_without_organization(outsider):
    built_in = LLMModel.objects.create(
        name="migration-built-in", is_custom=False, org=None, created_by=outsider
    )

    _apply_migration()

    assert LLMModel.objects.get(pk=built_in.pk).created_by_id == outsider.id


# ---- last edits ----


@pytest.mark.django_db
def test_clears_the_last_editor_who_is_not_a_member_keeping_the_time(
    acme_flow, member_only, superadmin, outsider
):
    outsider_note = GraphNote.objects.create(graph=acme_flow, content="outsider")
    member_note = GraphNote.objects.create(graph=acme_flow, content="member")
    superadmin_note = GraphNote.objects.create(graph=acme_flow, content="superadmin")
    record_last_edit(acme_flow, outsider, edited_at=EDITED_AT)
    record_last_edit(outsider_note, outsider, edited_at=EDITED_AT)
    record_last_edit(member_note, member_only, edited_at=EDITED_AT)
    record_last_edit(superadmin_note, superadmin, edited_at=EDITED_AT)

    _apply_migration()

    for released in (acme_flow, outsider_note):
        last_edit = _last_edit_of(released)
        assert last_edit.edited_by_id is None
        assert last_edit.edited_at == EDITED_AT
    assert _last_edit_of(member_note).edited_by_id == member_only.id
    assert _last_edit_of(superadmin_note).edited_by_id == superadmin.id


# ---- version snapshots ----


@pytest.mark.django_db
def test_scrubs_snapshot_entries_of_non_members_and_keeps_members_and_superadmins(
    beta, acme_flow, member_only, superadmin, outsider
):
    acme_version = GraphVersion.objects.create(
        graph=acme_flow,
        name="acme-v1",
        snapshot=_snapshot(
            authors={"1": outsider.id, "2": member_only.id, "3": superadmin.id, "4": None},
            editors={"1": member_only.id, "2": outsider.id},
        ),
    )
    deleted_version = GraphVersion.objects.create(
        graph=acme_flow,
        name="acme-deleted",
        snapshot=_snapshot(authors={"1": outsider.id}, editors={}),
        is_soft_deleted=True,
        soft_deleted_at=timezone.now(),
    )
    beta_version = GraphVersion.objects.create(
        graph=Graph.objects.create(name="beta-flow", org=beta),
        name="beta-v1",
        snapshot=_snapshot(authors={"1": outsider.id}, editors={"1": outsider.id}),
    )

    _apply_migration()

    assert GraphVersion.all_objects.get(pk=acme_version.pk).snapshot == _snapshot(
        authors={"1": None, "2": member_only.id, "3": superadmin.id, "4": None},
        editors={"1": member_only.id, "2": None},
    )
    assert GraphVersion.all_objects.get(pk=deleted_version.pk).snapshot == _snapshot(
        authors={"1": None}, editors={}
    )
    assert GraphVersion.all_objects.get(pk=beta_version.pk).snapshot == _snapshot(
        authors={"1": outsider.id}, editors={"1": outsider.id}
    )


@pytest.mark.django_db
def test_scrubs_snapshots_across_batches(acme_flow, outsider, monkeypatch):
    monkeypatch.setattr(migration_module, "_SNAPSHOT_BATCH_SIZE", 2)
    versions = [
        GraphVersion.objects.create(
            graph=acme_flow,
            name=f"batched-{index}",
            snapshot=_snapshot(authors={"1": outsider.id}, editors={}),
        )
        for index in range(5)
    ]

    assert migration_module.scrub_version_snapshots(_state_before_migration().apps) == 5
    for version in versions:
        assert GraphVersion.objects.get(pk=version.pk).snapshot == _snapshot(
            authors={"1": None}, editors={}
        )


# ---- idempotence ----


@pytest.mark.django_db
def test_running_it_twice_changes_nothing_the_second_time(
    acme, acme_flow, member_only, outsider
):
    Graph.objects.create(name="outsider-flow", org=acme, created_by=outsider)
    record_last_edit(acme_flow, outsider, edited_at=EDITED_AT)
    GraphVersion.objects.create(
        graph=acme_flow,
        name="v1",
        snapshot=_snapshot(
            authors={"1": outsider.id, "2": member_only.id}, editors={"1": outsider.id}
        ),
    )
    _apply_migration()
    snapshots_after_first_run = dict(GraphVersion.objects.values_list("pk", "snapshot"))

    historical_apps = _state_before_migration().apps

    assert migration_module.release_authors(historical_apps) == 0
    assert migration_module.release_last_edits(historical_apps) == 0
    assert migration_module.scrub_version_snapshots(historical_apps) == 0
    assert dict(GraphVersion.objects.values_list("pk", "snapshot")) == snapshots_after_first_run
