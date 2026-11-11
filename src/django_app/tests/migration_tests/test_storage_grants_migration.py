"""tables 0287 and storage_credentials 0002 add storage grants.

Invariants: a node that existed before the columns is not configured (all NULL), so
its runs keep today's access; the migration changes no data. A temporary account's
session link stops being one-to-one, so a session can hold one account per distinct
grant.
"""

import pytest
from django.utils import timezone
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

TABLES_BEFORE = ("tables", "0286_rename_filter_preset_org_indexes")
TABLES_AFTER = ("tables", "0287_storage_grants")
ACCOUNTS_BEFORE = ("storage_credentials", "0001_initial")
ACCOUNTS_AFTER = ("storage_credentials", "0002_session_accounts")


def _migrate(*targets):
    MigrationExecutor(connection).migrate(list(targets))
    return MigrationExecutor(connection).loader.project_state(list(targets)).apps


@pytest.fixture
def restore_latest_schema():
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_existing_nodes_are_not_configured_and_the_database_then_rejects_a_partial_slot(
    restore_latest_schema,
):
    old_apps = _migrate(TABLES_BEFORE, ACCOUNTS_BEFORE)
    organization = old_apps.get_model("rbac", "Organization").objects.create(name="grants-migration")
    graph = old_apps.get_model("tables", "Graph").objects.create(name="g", org=organization)
    task_pk = old_apps.get_model("tables", "TaskNode").objects.create(graph=graph).pk
    cdt_pk = old_apps.get_model("tables", "ClassificationDecisionTableNode").objects.create(graph=graph).pk

    new_apps = _migrate(TABLES_AFTER, ACCOUNTS_AFTER)

    task = new_apps.get_model("tables", "TaskNode").objects.get(pk=task_pk)
    cdt = new_apps.get_model("tables", "ClassificationDecisionTableNode").objects.get(pk=cdt_pk)
    assert (task.storage_grant_read, task.storage_grant_write, task.storage_grant_delete) == (
        None,
        None,
        None,
    )
    assert (cdt.pre_storage_grant_read, cdt.post_storage_grant_delete) == (None, None)
    with pytest.raises(IntegrityError), transaction.atomic():
        new_apps.get_model("tables", "TaskNode").objects.filter(pk=task_pk).update(
            storage_grant_read=True
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
