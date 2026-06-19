from database.repositories.base import AbstractSQLAlchemyRepository


class NaiveRagSQLAlchemyRepository(AbstractSQLAlchemyRepository):
    """Repository for naive RAG documents, chunks, and embeddings."""
