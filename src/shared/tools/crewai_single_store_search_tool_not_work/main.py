import sys
from typing import Any, List, Optional, Dict
from pydantic import BaseModel
from sqlalchemy.pool import QueuePool

try:
    from singlestoredb import connect
except ImportError:
    raise ImportError(
        "The 'singlestoredb' package is required. Install it via 'pip install singlestoredb'."
    )


class SingleStoreSearchToolSchema(BaseModel):
    search_query: str
    host: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    ssl_key: Optional[str] = None
    ssl_cert: Optional[str] = None
    ssl_ca: Optional[str] = None
    pool_size: int = 5
    max_overflow: int = 10
    timeout: float = 30
    tables: List[str] = []


class SingleStoreSearchTool:
    def __init__(self, args: SingleStoreSearchToolSchema):
        self.connection_args = {
            "host": args.host,
            "user": args.user,
            "password": args.password,
            "port": args.port,
            "database": args.database,
            "ssl_key": args.ssl_key,
            "ssl_cert": args.ssl_cert,
            "ssl_ca": args.ssl_ca,
        }

        self.pool = QueuePool(
            creator=self._create_connection,
            pool_size=args.pool_size,
            max_overflow=args.max_overflow,
            timeout=args.timeout,
        )
        self.tables = args.tables
        self.description = "SingleStore Search Tool"
        self._initialize_tables(self.tables)

    def _create_connection(self) -> Any:
        return connect(
            **{k: v for k, v in self.connection_args.items() if v is not None}
        )

    def _get_connection(self) -> Any:
        return self.pool.connect()

    def _validate_query(self, query: str) -> tuple[bool, str]:
        if not isinstance(query, str):
            return False, "Query must be a string."
        q = query.strip().lower()
        if not (q.startswith("select") or q.startswith("show")):
            return False, "Only SELECT and SHOW queries are supported."
        return True, "Valid query"

    def _initialize_tables(self, tables: List[str]):
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SHOW TABLES")
                existing_tables = {row[0] for row in cursor.fetchall()}
                if not existing_tables:
                    raise ValueError("No tables found in the database.")

                if not tables:
                    tables = list(existing_tables)

                table_definitions = []
                for table in tables:
                    if table not in existing_tables:
                        raise ValueError(f"Table {table} does not exist.")
                    cursor.execute(f"SHOW COLUMNS FROM {table}")
                    columns = cursor.fetchall()
                    col_info = ", ".join(f"{c[0]} {c[1]}" for c in columns)
                    table_definitions.append(f"{table}({col_info})")
                self.description = f"SingleStore Search Tool for tables: {', '.join(table_definitions)}"
        finally:
            conn.close()

    def run(self, query: str) -> str:
        valid, msg = self._validate_query(query)
        if not valid:
            return f"Invalid query: {msg}"

        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query)
                results = cursor.fetchall()
                if not results:
                    return "No results found."
                return "\n".join([", ".join(map(str, row)) for row in results])
        finally:
            conn.close()


def main(
    search_query: str,
    host: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    port: Optional[int] = None,
    database: Optional[str] = None,
    ssl_key: Optional[str] = None,
    ssl_cert: Optional[str] = None,
    ssl_ca: Optional[str] = None,
    pool_size: int = 5,
    max_overflow: int = 10,
    timeout: float = 30,
    tables: List[str] = [],
) -> str:
    args = SingleStoreSearchToolSchema(
        search_query=search_query,
        host=host,
        user=user,
        password=password,
        port=port,
        database=database,
        ssl_key=ssl_key,
        ssl_cert=ssl_cert,
        ssl_ca=ssl_ca,
        pool_size=pool_size,
        max_overflow=max_overflow,
        timeout=timeout,
        tables=tables,
    )
    tool = SingleStoreSearchTool(args)
    return tool.run(args.search_query)


if __name__ == "__main__":
    import json

    try:
        params = json.loads(sys.argv[1])
    except Exception:
        params = {}
    result = main(**params)
    print(result)
