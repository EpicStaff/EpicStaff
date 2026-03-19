from main import main

if __name__ == "__main__":
    search_query = input("Enter search query: ")
    website = input("Enter website URL: ")
    
    limit_input = input("Enter result limit (optional, press Enter to skip): ")
    limit = int(limit_input) if limit_input else None

    result = main(search_query=search_query, website=website, limit=limit)
    print("\nSearch Results:\n", result)