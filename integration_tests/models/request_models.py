from pydantic import BaseModel


class KnowledgeSearchMessage(BaseModel):
    collection_id: int
    rag_id: int
    rag_type: str
    uuid: str
    query: str
    rag_search_config: dict
