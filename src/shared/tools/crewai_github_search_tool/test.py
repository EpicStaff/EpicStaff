from main import main

if __name__ == "__main__":
    print("Local/Remote GitHub Search Tool Test")
    
    repo_path_or_url = input("Enter path to local repo or GitHub URL: ").strip()
    if not repo_path_or_url:
        print("Error: You must enter a local path or GitHub URL.")
        exit(1)
    
    query = input("Enter search query: ").strip()
    if not query:
        print("Error: You must enter a search query.")
        exit(1)
    
    file_types_input = input(
        "Enter file types to include (comma-separated, e.g., .py,.md) or leave blank for all: "
    ).strip()
    file_types = [ft.strip() for ft in file_types_input.split(",")] if file_types_input else None

    print("\nSearching...\n")
    result = main(search_query=query, repo_path_or_url=repo_path_or_url, file_types=file_types)
    
    print("\n=== Search Results ===")
    print(result)