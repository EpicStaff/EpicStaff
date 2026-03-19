from typing import Any, List
import sqlite3


def main(
    db_uri: str, table_name: str, search_query: str, limit: int | None = None
) -> List[Any]:
    """
    Search the table content for the given query.

    Args:
        db_uri (str): Database URI (sqlite path or MySQL connection string).
        table_name (str): Database table to search in.
        search_query (str): Query string to search for.
        limit (int | None): Optional limit of results.

    Returns:
        List[Any]: List of rows matching the query.
    """
    # Connect to SQLite database
    conn = sqlite3.connect(db_uri)
    cursor = conn.cursor()

    # Get columns of the table
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [col[1] for col in cursor.fetchall()]

    # Build simple LIKE search query
    query = f"SELECT * FROM {table_name} WHERE " + " OR ".join(
        [f"{col} LIKE ?" for col in columns]
    )
    params = [f"%{search_query}%"] * len(columns)
    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query, params)
    results = cursor.fetchall()
    conn.close()
    return results
