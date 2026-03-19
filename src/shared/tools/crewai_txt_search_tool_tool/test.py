from main import main

if __name__ == "__main__":
    txt_path = input("Enter TXT file path or URL: ")
    query = input("Enter search query: ")
    threshold = input("Enter similarity threshold (default 0.7): ")
    limit = input("Enter max number of results (default 5): ")

    threshold = float(threshold) if threshold else 0.7
    limit = int(limit) if limit else 5

    results = main(txt=txt_path, search_query=query, similarity_threshold=threshold, limit=limit)
    print("\nSearch Results:\n")
    print(results)