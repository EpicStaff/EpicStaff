"""tables 0287 and storage_credentials 0002 add storage grants.

Invariants: a node that existed before the columns gets every box ticked, so its runs
keep today's access, and a node created afterwards starts with every box unticked. File
Extractor and Audio to Text have a read box only; agent and task nodes have none. A
temporary account's session link stops being one-to-one, so a session can hold one
account per distinct grant.
"""

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

TABLES_BEFORE = ("tables", "0286_rename_filter_preset_org_indexes")
TABLES_AFTER = ("tables", "0287_storage_grants")
ACCOUNTS_BEFORE = ("storage_credentials", "0001_initial")
ACCOUNTS_AFTER = ("storage_credentials", "0002_session_accounts")

CODE_NODE_FLAGS = ("storage_grant_read", "storage_grant_write", "storage_grant_delete")
CDT_FLAGS = tuple(f"{slot}_{flag}" for slot in ("pre", "post") for flag in CODE_NODE_FLAGS)

MODEL_OF_NODE = {
    "python": "PythonNode",
    "webhook": "WebhookTriggerNode",
    "cdt": "ClassificationDecisionTableNode",
    "file_extractor": "FileExtractorNode",
    "audio": "AudioTranscriptionNode",
}


def _migrate(*targets):
    MigrationExecutor(connection).migrate(list(targets))
    return MigrationExecutor(connection).loader.project_state(list(targets)).apps


def _create_nodes(apps, graph_id):
    """One node of every grant type in the graph, keyed like MODEL_OF_NODE."""
    code = apps.get_model("tables", "PythonCode").objects.create(code="x", entrypoint="main")
    extra = {
        "python": {"python_code": code},
        "webhook": {"python_code": code, "node_name": f"hook-{code.pk}"},
    }
    return {
        name: apps.get_model("tables", model_name)
        .objects.create(graph_id=graph_id, **extra.get(name, {}))
        .pk
        for name, model_name in MODEL_OF_NODE.items()
    }


@pytest.fixture
def restore_latest_schema():
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.fixture
def migrated(restore_latest_schema):
    """The apps after 0287, the pks of nodes created before it, and the graph holding them."""
    old_apps = _migrate(TABLES_BEFORE, ACCOUNTS_BEFORE)
    organization = old_apps.get_model("rbac", "Organization").objects.create(
        name="grants-migration"
    )
    graph = old_apps.get_model("tables", "Graph").objects.create(name="g", org=organization)
    old_node_pks = _create_nodes(old_apps, graph.pk)
    new_apps = _migrate(TABLES_AFTER, ACCOUNTS_AFTER)
    return new_apps, old_node_pks, graph.pk


@pytest.mark.django_db(transaction=True)
def test_existing_grant_nodes_get_every_box(migrated):
    new_apps, node_pks, _ = migrated

    def stored(name):
        return new_apps.get_model("tables", MODEL_OF_NODE[name]).objects.get(pk=node_pks[name])

    for name in ("python", "webhook"):
        assert [getattr(stored(name), flag) for flag in CODE_NODE_FLAGS] == [True, True, True]
    assert [getattr(stored("cdt"), flag) for flag in CDT_FLAGS] == [True] * 6
    for name in ("file_extractor", "audio"):
        node = stored(name)
        assert node.storage_grant_read is True
        assert not hasattr(node, "storage_grant_write")
        assert not hasattr(node, "storage_grant_delete")


@pytest.mark.django_db(transaction=True)
def test_new_grant_nodes_start_with_none(migrated):
    new_apps, _, graph_pk = migrated

    created_pks = _create_nodes(new_apps, graph_pk)

    def created(name):
        return new_apps.get_model("tables", MODEL_OF_NODE[name]).objects.get(pk=created_pks[name])

    for name in ("python", "webhook"):
        assert [getattr(created(name), flag) for flag in CODE_NODE_FLAGS] == [False] * 3
    assert [getattr(created("cdt"), flag) for flag in CDT_FLAGS] == [False] * 6
    assert created("file_extractor").storage_grant_read is False
    assert created("audio").storage_grant_read is False


@pytest.mark.django_db(transaction=True)
def test_agent_and_task_nodes_have_no_grant(migrated):
    new_apps, _, _ = migrated

    for model_name in ("AgentNode", "TaskNode"):
        model = new_apps.get_model("tables", model_name)
        assert not [field.name for field in model._meta.fields if "storage_grant" in field.name]


@pytest.mark.django_db(transaction=True)
def test_the_grant_columns_reject_null(migrated):
    new_apps, node_pks, _ = migrated

    with pytest.raises(IntegrityError), transaction.atomic():
        new_apps.get_model("tables", "PythonNode").objects.filter(pk=node_pks["python"]).update(
            storage_grant_read=None
        )


@pytest.mark.django_db(transaction=True)
def test_a_session_can_hold_several_accounts_after_the_migration_but_not_before(
    restore_latest_schema,
):
    old_apps = _migrate(TABLES_BEFORE, ACCOUNTS_BEFORE)
    organization = old_apps.get_model("rbac", "Organization").objects.create(name="grants-accounts")
    graph = old_apps.get_model("tables", "Graph").objects.create(name="g", org=organization)
    session = old_apps.get_model("tables", "Session").objects.create(
        graph=graph, status_updated_at=timezone.now()
    )
    account_model = old_apps.get_model("storage_credentials", "TemporaryStorageAccount")
    account_model.objects.create(session=session, access_key="one")
    with pytest.raises(IntegrityError), transaction.atomic():
        account_model.objects.create(session=session, access_key="two")

    new_apps = _migrate(TABLES_AFTER, ACCOUNTS_AFTER)

    new_account_model = new_apps.get_model("storage_credentials", "TemporaryStorageAccount")
    new_account_model.objects.create(session_id=session.pk, access_key="two", shared_actions=["read"])
    assert new_account_model.objects.filter(session_id=session.pk).count() == 2
    assert new_account_model.objects.get(access_key="one").shared_actions is None
