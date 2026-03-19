# PG Search Tool (Standalone)

import psycopg2
from psycopg2.extras import RealDictCursor


def main(
    db_uri: str,
    table_name: str,
    search_query: str,
    limit: int = 10,
) -> str:
    """
    Perform a text search on a PostgreSQL table using ILIKE.

    Args:
        db_uri (str): PostgreSQL connection URI
        table_name (str): Table to search
        search_query (str): Search text
        limit (int): Max rows to return

    Returns:
        str: Query results or error message
    """
    try:
        conn = psycopg2.connect(db_uri)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        sql = f"""
        SELECT *
        FROM {table_name}
        WHERE CAST({table_name} AS TEXT) ILIKE %s
        LIMIT %s;
        """

        cursor.execute(sql, (f"%{search_query}%", limit))
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        if not rows:
            return "No results found."

        return "\n".join(str(row) for row in rows)

    except Exception as e:
        return f"ERROR: {str(e)}"