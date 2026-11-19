# PostgreSQL Search Tool

import re

import sqlparse
from epicstaff_common import require_setting, resolve_setting, safe_error_message

# The tool's venv is built by the operator; one built for the SQLAlchemy version
# of this tool has psycopg2 but not psycopg. psycopg is imported in run_query so
# that such a venv gets this message instead of an ImportError at module load.
PSYCOPG_MISSING_MESSAGE = (
    "psycopg is not installed in this tool's venv: add psycopg[binary] to it."
)

# libpq does not know SQLAlchemy's "+driver" part of the scheme
# ("postgresql+psycopg2://"), which configurations saved while the tool ran on
# SQLAlchemy still carry.
SQLALCHEMY_DRIVER_SCHEME = re.compile(r"^(postgres(?:ql)?)\+[^:/]+://")


class PostgreSQLSearchTool:
    def __init__(self):
        db_uri = require_setting(globals(), "db_uri")
        self.db_uri = SQLALCHEMY_DRIVER_SCHEME.sub(r"\1://", db_uri)
        self.read_only = resolve_setting(globals(), "read_only", True)

    def _validate_query(self, query: str):
        """Reject obvious misuse early with a readable message.

        Not the read-only boundary: sqlparse does not always split statements the
        way PostgreSQL does (a backslash in a standard string, for one), so the
        server enforces one statement and read-only mode in run_query.
        """
        query = query.strip()
        if not query:
            return False, "Empty SQL query."

        statements = [s.strip() for s in sqlparse.split(query) if s.strip()]
        if len(statements) != 1:
            return False, "Multiple statements are not allowed."

        parsed = sqlparse.parse(statements[0])
        if not parsed:
            return False, "Invalid SQL syntax."

        command = parsed[0].get_type().upper()
        if self.read_only and command != "SELECT":
            return (
                False,
                f"Only SELECT queries are allowed in read-only mode (got {command}).",
            )

        return True, ""

    def _format_result(self, cursor, sql_query):
        if cursor.description is not None:
            rows = cursor.fetchall()
            if not rows:
                return (
                    f'Query "{sql_query}" executed successfully, but returned no rows.'
                )
            return rows
        else:
            affected = cursor.rowcount if cursor.rowcount != -1 else 0
            return {
                "info": f'Query "{sql_query}" executed successfully. {affected} row(s) affected.'
            }

    def run_query(self, sql_query: str):
        """Run one statement; in read-only mode, in a READ ONLY transaction that is rolled back.

        In pipeline mode psycopg sends every query over the extended query
        protocol, where PostgreSQL refuses more than one statement. So the query
        can neither end the READ ONLY transaction psycopg opens for it
        (COMMIT; BEGIN READ WRITE) nor change the session's defaults ahead of a
        write. The rollback discards anything that still got through.

        prepare=False keeps the query in the unnamed statement, which the server
        replaces with the next one. A named prepared statement would outlive the
        transaction, also when the query fails, and behind a transaction-mode
        pooler the next client on that backend would collide with its name.

        Read-write mode only stops forcing read-only: psycopg then sends a plain
        BEGIN, so a role's or database's default_transaction_read_only still applies.
        """
        is_safe, error_msg = self._validate_query(sql_query)
        if not is_safe:
            return {"error": error_msg}

        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            return {"error": PSYCOPG_MISSING_MESSAGE}

        try:
            with psycopg.connect(self.db_uri, row_factory=dict_row) as connection:
                connection.read_only = True if self.read_only else None
                with connection.cursor() as cursor:
                    # Leaving the pipeline syncs it: a server error is raised
                    # there, and the cursor holds the results only after it.
                    with connection.pipeline():
                        cursor.execute(sql_query, prepare=False)
                    result = self._format_result(cursor, sql_query)
                if self.read_only:
                    connection.rollback()
                else:
                    connection.commit()
                return result
        except Exception as e:
            return {"error": safe_error_message(e)}


def main(sql_query, **kwargs):
    try:
        executor = PostgreSQLSearchTool()
        return executor.run_query(sql_query)
    except Exception as error:
        return {"error": safe_error_message(error)}
