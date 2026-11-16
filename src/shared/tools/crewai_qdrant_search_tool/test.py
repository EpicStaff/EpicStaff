import main as tool


if __name__ == "__main__":
    # The sandbox injects tool configuration values as module globals.
    tool.qdrant_url = "http://localhost:6333"
    tool.qdrant_api_key = ""
    tool.openai_api_key = "PASTE_OPENAI_KEY_HERE"

    result = tool.main(
        query="What is vector search?",
        collection_name="test_collection",
        limit=2,
    )

    print(result)
