from main import main

def test():
    search_query = input("Enter search query: ")
    xml = input("Enter XML file path or URL: ")
    limit_input = input("Enter max number of results (leave blank for no limit): ")
    limit = int(limit_input) if limit_input.strip() else None

    result = main(search_query=search_query, xml=xml, limit=limit)
    print("\nSearch Results:\n")
    print(result)

if __name__ == "__main__":
    test()