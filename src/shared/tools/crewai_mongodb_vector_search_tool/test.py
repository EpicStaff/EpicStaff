from main import main

main(
    query="Tell me about OpenAI",
    openai_api_key="YOUR_OPENAI_API_KEY",
    connection_string="mongodb://localhost:27017",
    database_name="test_db",
    collection_name="test_collection",
    vector_index_name="vector_index",
    text_key="text",
    embedding_key="embedding",
    dimensions=1536,
    embedding_model="text-embedding-3-large",
    limit=4,
    oversampling_factor=10,
    include_embeddings=False,
)