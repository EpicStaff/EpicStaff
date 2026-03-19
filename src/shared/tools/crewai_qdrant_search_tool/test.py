from main import main


if __name__ == "__main__":
    result = main(
        query="What is vector search?",
        collection_name="test_collection",
        qdrant_url="http://localhost:6333",
        qdrant_api_key="",
        openai_api_key="PASTE_OPENAI_KEY_HERE",
        limit=2,
    )

    print(result)