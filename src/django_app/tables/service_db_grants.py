"""Table and sequence privileges of the services' restricted database roles.

manager, knowledge and realtime connect to the shared database with their own roles, which
crewdb creates with no table access at all. This module is the only place that says which
tables and sequences each role may touch and how; the ``apply_service_grants`` management
command applies it right after ``migrate``. It lives in django_app because the tables it
names are django_app's schema. Every table listed here must exist once the migrations have
run: a missing one fails the command rather than leaving a role without the access its
service needs. It imports nothing from Django: it is data and SQL text, testable without a
database.
"""

from dataclasses import dataclass

SELECT = "SELECT"
INSERT = "INSERT"
UPDATE = "UPDATE"
DELETE = "DELETE"
USAGE = "USAGE"

READ_WRITE = (SELECT, INSERT, UPDATE, DELETE)


@dataclass(frozen=True)
class TableGrant:
    """Privileges on one table.

    Attributes:
        privileges: Table-level privileges, e.g. ``("SELECT", "DELETE")``.
        update_columns: Columns granted UPDATE on their own, for a role that may change
            only those columns of the table.
    """

    table: str
    privileges: tuple[str, ...]
    update_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class SequenceGrant:
    sequence: str
    privileges: tuple[str, ...]


@dataclass(frozen=True)
class ServiceRoleGrants:
    """Everything one service's role is granted.

    Attributes:
        service: Service name, for log messages.
        role_variable: Environment variable holding the role's name, e.g. ``MANAGER_DB_USER``.
    """

    service: str
    role_variable: str
    tables: tuple[TableGrant, ...]
    sequences: tuple[SequenceGrant, ...] = ()


MANAGER_GRANTS = ServiceRoleGrants(
    service="manager",
    role_variable="MANAGER_DB_USER",
    tables=(
        # The retention job deletes expired sessions. Its FOR UPDATE SKIP LOCKED needs UPDATE
        # on at least one column.
        TableGrant("tables_session", (SELECT, DELETE), update_columns=("finished_at",)),
        # ScheduleService reads the schedule triggers and records their runs.
        TableGrant("tables_scheduletriggernode", (SELECT, UPDATE)),
        # Deleted by the temporary storage credentials cleanup and with their session.
        TableGrant("storage_credentials_temp_account", (SELECT, DELETE)),
        # The temporary storage credentials cleanup reads when a run finished
        # (finished_at, ended_at).
        TableGrant("tables_pythoncoderesult", (SELECT,)),
        TableGrant("realtime_agent_chat", (SELECT,)),
        # The retention job reads each organization's retention settings and its flows.
        TableGrant("rbac_organization", (SELECT,)),
        TableGrant("rbac_organization_config", (SELECT,)),
        TableGrant("tables_graph", (SELECT,)),
        # Rows the retention job deletes with their session (SESSION_CHILD_TABLES in
        # src/shared/retention.py).
        TableGrant("tables_graphsessionmessage", (SELECT, DELETE)),
        TableGrant("tables_usersessionmessage", (SELECT, DELETE)),
        TableGrant("tables_agentsessionmessage", (SELECT, DELETE)),
        TableGrant("tables_tasksessionmessage", (SELECT, DELETE)),
        TableGrant("tables_sessionwarningmessage", (SELECT, DELETE)),
        TableGrant("tables_sessionprincipal", (SELECT, DELETE)),
        TableGrant("tables_sessioncallback", (SELECT, DELETE)),
        TableGrant("tables_sessionstoragefile", (SELECT, DELETE)),
        # Retention also clears the link to a deleted parent session.
        TableGrant(
            "tables_sessiontrigger",
            (SELECT, DELETE),
            update_columns=("triggered_by_session_id",),
        ),
        # Retention only clears the link to a deleted session.
        TableGrant(
            "tables_keyvaluetableentry",
            (SELECT,),
            update_columns=("updated_by_session_id",),
        ),
    ),
)

KNOWLEDGE_GRANTS = ServiceRoleGrants(
    service="knowledge",
    role_variable="KNOWLEDGE_DB_USER",
    tables=(
        # Configuration the knowledge service reads but never changes.
        TableGrant("tables_provider", (SELECT,)),
        TableGrant("tables_embeddingmodel", (SELECT,)),
        TableGrant("tables_embeddingconfig", (SELECT,)),
        TableGrant("tables_sourcecollection", (SELECT,)),
        TableGrant("tables_documentmetadata", (SELECT,)),
        TableGrant("tables_documentcontent", (SELECT,)),
        TableGrant("tables_baseragtype", (SELECT,)),
        TableGrant("tables_llmconfig", (SELECT,)),
        TableGrant("tables_llmmodel", (SELECT,)),
        # Rows django_app creates and the knowledge service updates while it indexes
        # (status, indexing usage), but never inserts or deletes.
        TableGrant("tables_naiverag", (SELECT, UPDATE)),
        TableGrant("tables_naiveragdocumentconfig", (SELECT, UPDATE)),
        # Written by the knowledge service while it indexes.
        TableGrant("tables_naiveragchunk", READ_WRITE),
        TableGrant("tables_naiveragpreviewchunk", READ_WRITE),
        TableGrant("tables_naiveragembedding", READ_WRITE),
        TableGrant("graph_rag", READ_WRITE),
        TableGrant("graph_rag_index_config", READ_WRITE),
        TableGrant("graph_rag_document", READ_WRITE),
    ),
    sequences=(SequenceGrant("tables_naiveragchunk_chunk_id_seq", (USAGE, SELECT, UPDATE)),),
)

REALTIME_GRANTS = ServiceRoleGrants(
    service="realtime",
    role_variable="REALTIME_DB_USER",
    tables=(TableGrant("realtime_session_items", READ_WRITE),),
    sequences=(SequenceGrant("realtime_session_items_id_seq", (USAGE,)),),
)

SERVICE_ROLE_GRANTS: tuple[ServiceRoleGrants, ...] = (
    MANAGER_GRANTS,
    KNOWLEDGE_GRANTS,
    REALTIME_GRANTS,
)


def quote_identifier(name: str) -> str:
    """Quote a Postgres identifier, doubling any embedded double quote."""
    return '"' + name.replace('"', '""') + '"'


def grant_statements(grants: ServiceRoleGrants, role: str) -> list[str]:
    """Return the SQL that gives ``role`` exactly the privileges in ``grants``.

    Each table and sequence is first stripped of everything the role holds on it (REVOKE ALL
    on a table also drops its column privileges), then granted again, so running the
    statements brings a database granted by any earlier matrix to this one. Run them in a
    single transaction: a service connected meanwhile then never sees an object between its
    REVOKE and its GRANT.
    """
    quoted_role = quote_identifier(role)
    statements: list[str] = []
    for table_grant in grants.tables:
        table = quote_identifier(table_grant.table)
        statements.append(f"REVOKE ALL ON TABLE {table} FROM {quoted_role}")
        statements.append(
            f"GRANT {', '.join(table_grant.privileges)} ON TABLE {table} TO {quoted_role}"
        )
        if table_grant.update_columns:
            columns = ", ".join(quote_identifier(column) for column in table_grant.update_columns)
            statements.append(f"GRANT UPDATE ({columns}) ON TABLE {table} TO {quoted_role}")
    for sequence_grant in grants.sequences:
        sequence = quote_identifier(sequence_grant.sequence)
        statements.append(f"REVOKE ALL ON SEQUENCE {sequence} FROM {quoted_role}")
        statements.append(
            f"GRANT {', '.join(sequence_grant.privileges)} ON SEQUENCE {sequence} TO {quoted_role}"
        )
    return statements
