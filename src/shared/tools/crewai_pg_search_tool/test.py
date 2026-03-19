from main import main

if __name__ == "__main__":
    print("PostgreSQL Search Tool Test")

    db_uri = input("Enter PostgreSQL URI: ").strip()
    table_name = input("Enter table name: ").strip()
    search_query = input("Enter search query: ").strip()

    result = main(
        db_uri=db_uri,
        table_name=table_name,
        search_query=search_query,
        limit=5,
    )

    print("\nRESULT:")
    print(result)