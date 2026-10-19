# PostgreSQL Search Tool

from epicstaff_common import require_setting, resolve_setting, safe_error_message
from sqlalchemy import create_engine, event, text
import sqlparse

READ_ONLY_STATEMENT = "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"


class PostgreSQLSearchTool:
    def __init__(self):
        self.db_uri = require_setting(globals(), "db_uri")
        self.read_only = resolve_setting(globals(), "read_only", True)
        self.engine = create_engine(self.db_uri)

        if self.read_only:
            @event.listens_for(self.engine, "connect")
            def _enforce_read_only(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute(READ_ONLY_STATEMENT)
                cursor.close()
                dbapi_connection.commit()

    def _validate_query(self, query: str):
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

    def _format_result(self, result, sql_query):
        if result.returns_rows:
            rows = [dict(r) for r in result.mappings()]
            if not rows:
                return (
                    f'Query "{sql_query}" executed successfully, but returned no rows.'
                )
            return rows
        else:
            affected = result.rowcount if result.rowcount != -1 else 0
            return {
                "info": f'Query "{sql_query}" executed successfully. {affected} row(s) affected.'
            }

    def run_query(self, sql_query: str):
        is_safe, error_msg = self._validate_query(sql_query)
        if not is_safe:
            return {"error": error_msg}

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql_query))
                conn.commit()
                return self._format_result(result, sql_query)
        except Exception as e:
            return {"error": safe_error_message(e)}


def main(sql_query, **kwargs):
    try:
        executor = PostgreSQLSearchTool()
        return executor.run_query(sql_query)
    except Exception as error:
        return {"error": safe_error_message(error)}
