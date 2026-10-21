"""tables 0271 adds PythonCode.execution_timeout.

Invariant: a PythonCode that existed before the column gets the deployment default
(SANDBOX_DEFAULT_EXECUTION_TIMEOUT) as it is when the migration runs, not a value frozen
into the migration file; there is no separate backfill. Reverting drops the column and
keeps the rows.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("tables", "0274_merge_20261021_1305")]
AFTER = [("tables", "0275_pythoncode_execution_timeout")]

# Distinct from any configured default, so a value frozen into the migration would fail.
DEFAULT_SECONDS = 45


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _column_names() -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, "tables_pythoncode")
    return {column.name for column in description}


@pytest.mark.django_db(transaction=True)
def test_existing_code_gets_the_deployment_default_and_revert_keeps_it(settings):
    settings.DEFAULT_EXECUTION_TIMEOUT_SECONDS = DEFAULT_SECONDS
    try:
        old_apps = _migrate(BEFORE)
        python_code_pk = (
            old_apps.get_model("tables", "PythonCode")
            .objects.create(code="def main(): return 1", entrypoint="main", libraries="")
            .pk
        )

        new_apps = _migrate(AFTER)
        migrated = new_apps.get_model("tables", "PythonCode").objects.get(pk=python_code_pk)
        assert migrated.execution_timeout == DEFAULT_SECONDS

        reverted_apps = _migrate(BEFORE)
        assert "execution_timeout" not in _column_names()
        reverted_model = reverted_apps.get_model("tables", "PythonCode")
        assert reverted_model.objects.filter(pk=python_code_pk).exists()
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
