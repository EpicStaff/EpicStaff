from ai_models.management.commands import upload_models


def seed_builtin_models() -> None:
    """Seed the providers and built-in LLM and embedding rows from the committed catalog, as container start does."""
    upload_models.upload_providers()
    upload_models.upload_llm_models()
    upload_models.upload_embedding_models()
