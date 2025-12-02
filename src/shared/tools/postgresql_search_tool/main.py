# PostgreSQL Search Tool

from sqlalchemy import create_engine, text
import sqlparse

class PostgreSQLSearchTool:
    def __init__(self):
        self.db_uri = state["variables"]["DB_URI"]
        self.read_only = state["variables"]["READ_ONLY"]
        self.engine = create_engine(self.db_uri)

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
            return False, f"Only SELECT queries are allowed in read-only mode (got {command})."

        return True, ""

    def _format_result(self, result, sql_query):
        if result.returns_rows:
            rows = [dict(r) for r in result.mappings()]
            if not rows:
                return f"Query \"{sql_query}\" executed successfully, but returned no rows."
            return rows
        else:
            affected = result.rowcount if result.rowcount != -1 else 0
            return {"info": f"Query \"{sql_query}\" executed successfully. {affected} row(s) affected."}

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
            return {"error": str(e)}


def main(sql_query):
    executor = PostgreSQLSearchTool()
    return executor.run_query(sql_query)
