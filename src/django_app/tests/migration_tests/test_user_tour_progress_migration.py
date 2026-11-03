"""tables 0280 moves the Quick Start completion off the user row into tour progress rows.

Forward: every non-null `quickstart_tour_completed_at` becomes a "quick-start" row with
the same time, and the column is dropped. Backward: the column comes back filled from the
"quick-start" rows; other tours have nowhere to go and are dropped with the table.

A database upgrading from main runs 0259 first, which marks every existing user as having
completed the Quick Start tour; 0280 must carry that into a "quick-start" row, or every
existing user gets the tour auto-started after the upgrade.
"""

from datetime import UTC, datetime
from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

quickstart_column_migration = import_module("tables.migrations.0259_user_quickstart_tour_completed_at")

BEFORE = [("tables", "0283_clear_local_avatars")]
AFTER = [("tables", "0284_user_tour_progress")]

FIRST_COMPLETION = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
LATER_COMPLETION = datetime(2026, 11, 12, 13, 14, 15, tzinfo=UTC)


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _user_columns() -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, "rbac_user")
    return {column.name for column in description}


@pytest.mark.django_db(transaction=True)
def test_quick_start_completion_is_copied_to_tour_progress_and_back():
    try:
        old_apps = _migrate(BEFORE)
        old_user_model = old_apps.get_model("tables", "User")
        completed_pk = old_user_model.objects.create(
            email="completed@migration.test", password="!", quickstart_tour_completed_at=FIRST_COMPLETION
        ).pk
        pending_pk = old_user_model.objects.create(email="pending@migration.test", password="!").pk
        other_tour_only_pk = old_user_model.objects.create(email="other-tour@migration.test", password="!").pk

        new_apps = _migrate(AFTER)
        assert "quickstart_tour_completed_at" not in _user_columns()
        progress_model = new_apps.get_model("tables", "UserTourProgress")
        copied = progress_model.objects.filter(user_id__in=[completed_pk, pending_pk, other_tour_only_pk])
        assert list(copied.values_list("user_id", "tour_key", "completed_at")) == [
            (completed_pk, "quick-start", FIRST_COMPLETION)
        ]

        progress_model.objects.create(user_id=completed_pk, tour_key="flows", completed_at=LATER_COMPLETION)
        progress_model.objects.create(user_id=pending_pk, tour_key="quick-start", completed_at=LATER_COMPLETION)
        progress_model.objects.create(user_id=other_tour_only_pk, tour_key="flows", completed_at=LATER_COMPLETION)

        reverted_apps = _migrate(BEFORE)
        reverted_user_model = reverted_apps.get_model("tables", "User")
        restored = reverted_user_model.objects.filter(pk__in=[completed_pk, pending_pk, other_tour_only_pk])
        assert dict(restored.values_list("pk", "quickstart_tour_completed_at")) == {
            completed_pk: FIRST_COMPLETION,
            pending_pk: LATER_COMPLETION,
            other_tour_only_pk: None,
        }
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_a_user_from_a_main_install_keeps_the_quick_start_tour_completed():
    try:
        old_apps = _migrate(BEFORE)
        old_user_model = old_apps.get_model("tables", "User")
        existing_user_pk = old_user_model.objects.create(email="from-main@migration.test", password="!").pk
        quickstart_column_migration.mark_existing_users_tour_completed(old_apps, None)
        backfilled_at = old_user_model.objects.get(pk=existing_user_pk).quickstart_tour_completed_at

        new_apps = _migrate(AFTER)
        progress = new_apps.get_model("tables", "UserTourProgress").objects.filter(user_id=existing_user_pk)
        assert list(progress.values_list("tour_key", "completed_at")) == [("quick-start", backfilled_at)]
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
