"""The manager role is granted every table the retention job touches, in all three places.

A table missing from the grants only shows up at night, as "permission denied" for every
organization; these tests make it fail when the session-tree contract changes instead.
"""

import pytest

from src.shared.retention import SESSION_CHILD_TABLES, SESSION_SET_NULL_COLUMNS
from tests.crewdb_entrypoint import (
    ENTRYPOINT,
    required_tables,
    tables_in_auto_grant_trigger,
    tables_in_grant_function,
)

RETENTION_TABLES = (
    {"tables_session", "tables_graph", "rbac_organization", "rbac_organization_retention"}
    | {link.table for link in SESSION_CHILD_TABLES}
    | {link.table for link in SESSION_SET_NULL_COLUMNS}
)


@pytest.mark.parametrize(
    ("place", "read_tables", "expected"),
    [
        ("grant_manager_permissions", tables_in_grant_function, RETENTION_TABLES),
        ("auto_grant_table_permissions", tables_in_auto_grant_trigger, RETENTION_TABLES),
        ("REQUIRED_TABLES", required_tables, RETENTION_TABLES),
    ],
)
def test_every_retention_table_is_granted(place, read_tables, expected):
    missing = expected - read_tables()

    assert not missing, f"{sorted(missing)} missing from {place} in {ENTRYPOINT}"


def test_grant_function_and_auto_grant_trigger_cover_the_same_tables():
    assert tables_in_grant_function() == tables_in_auto_grant_trigger()
