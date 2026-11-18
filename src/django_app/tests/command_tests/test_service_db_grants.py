from tables.service_db_grants import (
    DELETE,
    SELECT,
    UPDATE,
    ServiceRoleGrants,
    TableGrant,
    grant_statements,
)


def _statements(*table_grants: TableGrant) -> list[str]:
    return grant_statements(
        ServiceRoleGrants(service="test", role_variable="TEST_DB_USER", tables=table_grants),
        "test_role",
    )


def test_table_level_privileges():
    assert _statements(TableGrant("tables_session", (SELECT, UPDATE))) == [
        'REVOKE ALL ON TABLE "tables_session" FROM "test_role"',
        'GRANT SELECT, UPDATE ON TABLE "tables_session" TO "test_role"',
    ]


def test_select_columns_only_grants_no_table_level_privilege():
    assert _statements(TableGrant("tables_llmmodel", (), select_columns=("id", "name"))) == [
        'REVOKE ALL ON TABLE "tables_llmmodel" FROM "test_role"',
        'GRANT SELECT ("id", "name") ON TABLE "tables_llmmodel" TO "test_role"',
    ]


def test_select_and_update_columns_next_to_table_level_privilege():
    table_grant = TableGrant(
        "tables_session", (DELETE,), select_columns=("id",), update_columns=("finished_at",)
    )

    assert _statements(table_grant) == [
        'REVOKE ALL ON TABLE "tables_session" FROM "test_role"',
        'GRANT DELETE ON TABLE "tables_session" TO "test_role"',
        'GRANT SELECT ("id") ON TABLE "tables_session" TO "test_role"',
        'GRANT UPDATE ("finished_at") ON TABLE "tables_session" TO "test_role"',
    ]


def test_column_names_are_quoted():
    assert _statements(TableGrant("t", (), select_columns=('we"ird',)))[-1] == (
        'GRANT SELECT ("we""ird") ON TABLE "t" TO "test_role"'
    )
