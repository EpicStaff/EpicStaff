from main import main

import sqlite3

# Setup test SQLite DB
db_uri = "test.db"
conn = sqlite3.connect(db_uri)
cursor = conn.cursor()
cursor.execute(
    "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)"
)
cursor.execute("INSERT INTO users (name, email) VALUES ('Alice', 'alice@example.com')")
cursor.execute("INSERT INTO users (name, email) VALUES ('Bob', 'bob@example.com')")
conn.commit()
conn.close()

# Run main directly with arguments
results = main(db_uri=db_uri, table_name="users", search_query="Alice", limit=10)

print("Search results:", results)
