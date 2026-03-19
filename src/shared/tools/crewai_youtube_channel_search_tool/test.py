from main import main

if __name__ == "__main__":
    # Ask user for parameters
    search_query = input("Enter search query: ")
    youtube_channel_handle = input("Enter youtube_channel_handle (with or without @): ")
    
    sim_thresh_input = input("Enter similarity_threshold (or leave empty): ")
    similarity_threshold = float(sim_thresh_input) if sim_thresh_input else None
    
    limit_input = input("Enter limit (or leave empty): ")
    limit = int(limit_input) if limit_input else None

    output = main(
        search_query=search_query,
        youtube_channel_handle=youtube_channel_handle,
        similarity_threshold=similarity_threshold,
        limit=limit
    )
    print("\nSearch Results:\n")
    print(output)