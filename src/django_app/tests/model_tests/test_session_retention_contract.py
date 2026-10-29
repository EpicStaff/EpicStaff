"""The manager deletes expired sessions with raw SQL, so Django's cascade emulation does not run.

Django performs on_delete=CASCADE / SET_NULL in Python; the database foreign keys do not.
The manager therefore has to know every table reachable from tables_session, which these
tests derive from the model metadata and compare with the shared contract, and its database
role has to be granted every one of those tables.
"""

from django.db import models
from src.shared.retention import (
    FINAL_SESSION_CALLBACK_STATUSES,
    SESSION_CHILD_TABLES,
    SESSION_PARENT_COLUMN,
    SESSION_SET_NULL_COLUMNS,
    TERMINAL_SESSION_STATUSES,
    SessionTreeLink,
)
from tables.models import Session, SessionCallback
from tables.service_db_grants import MANAGER_GRANTS
from tables.services.session_callbacks.service import TERMINAL_STATUSES

ACTIVE_SESSION_STATUSES = {"pending", "run", "wait_for_user"}
UNDELIVERED_CALLBACK_STATUSES = {"registered", "pending"}

UPDATE_CONTRACT = (
    "Update src/shared/retention.py and the manager role's grants in "
    "src/django_app/tables/service_db_grants.py (MANAGER_GRANTS)."
)
TEACH_REPOSITORY = (
    "The manager's raw delete (RetentionRepository) handles only CASCADE (deleted) and SET_NULL "
    "(cleared) foreign keys pointing directly at tables_session. Teach RetentionRepository the "
    "new relation. " + UPDATE_CONTRACT
)


def _reverse_relations(model: type[models.Model]) -> list[models.ForeignObjectRel]:
    # include_hidden: related_name="+" relations (SessionTrigger.triggered_by_session,
    # KeyValueTableEntry.updated_by_session) are absent from _meta.related_objects.
    # Reverse many-to-many relations are skipped: their through table's foreign key is
    # reported on its own as a hidden one-to-many relation.
    return [
        field
        for field in model._meta.get_fields(include_hidden=True)
        if field.auto_created and not field.concrete and not field.many_to_many
    ]


def _describe(relation: models.ForeignObjectRel, parent: type[models.Model]) -> str:
    return (
        f"{relation.related_model._meta.db_table}.{relation.field.column} -> "
        f"{parent._meta.db_table}.{relation.field.target_field.column} "
        f"(on_delete={relation.on_delete.__name__})"
    )


def _walk_session_tree() -> tuple[set[SessionTreeLink], set[SessionTreeLink], list[str]]:
    """Return (cascaded links, SET_NULL links, unsupported relations) reachable from Session."""
    cascaded: set[SessionTreeLink] = set()
    set_null: set[SessionTreeLink] = set()
    unsupported: list[str] = []
    visited: set[type[models.Model]] = set()

    def visit(parent: type[models.Model]) -> None:
        visited.add(parent)
        for relation in _reverse_relations(parent):
            child = relation.related_model
            description = _describe(relation, parent)
            if parent is not Session:
                # Anything hanging off a child table (cascaded, cleared or protected) is
                # beyond what the manager's delete does.
                unsupported.append(f"{description}: points at a child table, not tables_session")
                continue
            if relation.field.target_field.column != "id":
                unsupported.append(f"{description}: points at a column other than id")
                continue
            link = SessionTreeLink(child._meta.db_table, relation.field.column)
            if relation.on_delete is models.CASCADE:
                if child is Session:
                    if link.column != SESSION_PARENT_COLUMN:
                        unsupported.append(f"{description}: a second self-reference")
                    continue
                cascaded.add(link)
                if child not in visited:
                    visit(child)
            elif relation.on_delete is models.SET_NULL:
                set_null.add(link)
            else:
                unsupported.append(f"{description}: only CASCADE and SET_NULL are supported")

    visit(Session)
    return cascaded, set_null, unsupported


def test_session_tree_has_only_direct_cascade_and_set_null_relations():
    _, _, unsupported = _walk_session_tree()

    assert unsupported == [], f"{unsupported}\n{TEACH_REPOSITORY}"


def test_child_tables_match_every_cascade_from_session():
    cascaded, _, _ = _walk_session_tree()

    assert set(SESSION_CHILD_TABLES) == cascaded, UPDATE_CONTRACT
    assert len(SESSION_CHILD_TABLES) == len(set(SESSION_CHILD_TABLES))


def test_set_null_columns_match_every_set_null_to_session():
    _, set_null, _ = _walk_session_tree()

    assert set(SESSION_SET_NULL_COLUMNS) == set_null, UPDATE_CONTRACT


def test_parent_column_is_the_session_self_reference():
    field = Session._meta.get_field("parent_session")

    assert field.column == SESSION_PARENT_COLUMN
    assert field.remote_field.on_delete is models.CASCADE


def test_terminal_statuses_match_django():
    every_status = {status.value for status in Session.SessionStatus}

    assert TERMINAL_SESSION_STATUSES == {status.value for status in TERMINAL_STATUSES}
    # A new status must be classified here, or the job would never (or wrongly) delete it.
    assert TERMINAL_SESSION_STATUSES | ACTIVE_SESSION_STATUSES == every_status
    assert TERMINAL_SESSION_STATUSES.isdisjoint(ACTIVE_SESSION_STATUSES)


def test_final_callback_statuses_match_django():
    every_status = {status.value for status in SessionCallback.Status}

    assert FINAL_SESSION_CALLBACK_STATUSES | UNDELIVERED_CALLBACK_STATUSES == every_status
    assert FINAL_SESSION_CALLBACK_STATUSES.isdisjoint(UNDELIVERED_CALLBACK_STATUSES)


def test_manager_role_is_granted_every_retention_table():
    # A table missing from the grants only shows up at night, as "permission denied" for
    # every organization.
    retention_tables = (
        {"tables_session", "tables_graph", "rbac_organization", "rbac_organization_config"}
        | {link.table for link in SESSION_CHILD_TABLES}
        | {link.table for link in SESSION_SET_NULL_COLUMNS}
    )
    granted = {table_grant.table for table_grant in MANAGER_GRANTS.tables}

    assert retention_tables <= granted, (
        f"{sorted(retention_tables - granted)} not granted to the manager role. " + UPDATE_CONTRACT
    )
