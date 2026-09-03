from contextlib import contextmanager
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, Session

from src.shared.envtools import Env
from storage import ORMNaiveRagStorage, ORMGraphRagStorage


BASE_DIR = Path(__file__).resolve().parent

env = Env()
if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(BASE_DIR / "../.env")

DEBUG = False

DB_USER = env.str("KNOWLEDGE_DB_USER")
DB_PASSWORD = env.str("KNOWLEDGE_DB_PASSWORD")
DB_NAME = env.str("DB_NAME")
DB_PORT = env.str("DB_PORT")
DB_HOST = env.str("DB_HOST")

REDIS_HOST = env.str("REDIS_HOST")
REDIS_PORT = env.int("REDIS_PORT")
REDIS_USER = env.str("REDIS_USER")
REDIS_PASSWORD = env.str("REDIS_PASSWORD")

KNOWLEDGE_SOURCES_CHANNEL = env.str("KNOWLEDGE_SOURCES_CHANNEL")
KNOWLEDGE_SEARCH_REQUEST_CHANNEL = env.str("KNOWLEDGE_SEARCH_REQUEST_CHANNEL")
KNOWLEDGE_SEARCH_RESPONSE_CHANNEL = env.str("KNOWLEDGE_SEARCH_RESPONSE_CHANNEL")
KNOWLEDGE_DOCUMENT_CHUNK_CHANNEL = env.str("KNOWLEDGE_DOCUMENT_CHUNK_REQUEST_CHANNEL")
KNOWLEDGE_DOCUMENT_CHUNK_RESPONSE = env.str("KNOWLEDGE_DOCUMENT_CHUNK_RESPONSE_CHANNEL")
KNOWLEDGE_INDEXING_CHANNEL = env.str("KNOWLEDGE_INDEXING_CHANNEL")

GRAPH_DATA_DIR = env.str("KNOWLEDGE_GRAPH_DATA_DIR")

KNOWLEDGE_MAX_EXTRACTION_INPUT_SIZE = env.byte_size("KNOWLEDGE_MAX_EXTRACTION_INPUT_SIZE")
KNOWLEDGE_MAX_EXTRACTION_UNPACKED_SIZE = env.byte_size("KNOWLEDGE_MAX_EXTRACTION_UNPACKED_SIZE")
KNOWLEDGE_MAX_EXTRACTION_CONTENT_SIZE = env.byte_size("KNOWLEDGE_MAX_EXTRACTION_CONTENT_SIZE")
KNOWLEDGE_MAX_EXTRACTION_HTML_SIZE = env.byte_size("KNOWLEDGE_MAX_EXTRACTION_HTML_SIZE")
KNOWLEDGE_MAX_EXTRACTION_PAGES = env.int("KNOWLEDGE_MAX_EXTRACTION_PAGES")

OPENAI_API_KEY = env.str("OPENAI_API_KEY", "")
MISTRAL_API_KEY = env.str("MISTRAL_API_KEY", "")
TOGETHER_API_KEY = env.str("TOGETHER_API_KEY", "")
COHERE_API_KEY = env.str("COHERE_API_KEY", "")
GOOGLE_API_KEY = env.str("GOOGLE_API_KEY", "")
CUSTOM_EMBED_BASE_URL = env.str("CUSTOM_EMBED_BASE_URL", "")
CUSTOM_EMBED_API_KEY = env.str("CUSTOM_EMBED_API_KEY", "")
EMBEDDING_HEADERS = env.str("KNOWLEDGE_EMBEDDING_HEADERS", "")

DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

ENGINE = create_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)

SessionLocal = scoped_session(sessionmaker(bind=ENGINE))


class UnitOfWork:
    """
    Unit of Work pattern for managing database transactions.

    Provides a single session context with storage repositories:
    - naive_rag_storage: NaiveRag-specific operations (ORMNaiveRagStorage)

    Key Design:
    - ONE session per UnitOfWork (no nested sessions)
    - Context can be passed to services for operations within the same transaction
    - Automatically commits on success, rolls back on exception

    Usage Pattern 1 - Direct storage access:
        with UnitOfWork().start() as uow_ctx:
            chunks = uow_ctx.naive_rag_storage.save_document_chunks(config_id, chunk_list)

    Usage Pattern 2 - Pass context to services (RECOMMENDED):
        with UnitOfWork().start() as uow_ctx:
            # Pass context to service - everything in same transaction
            chunk_data = ChunkDocumentService().process_chunk_document_in_session(
                uow_ctx=uow_ctx,
                naive_rag_document_config_id=config_id
            )
    """

    def __init__(self):
        self.session: Session | None = None
        self.naive_rag_storage: ORMNaiveRagStorage | None = None
        self.graph_rag_storage: ORMGraphRagStorage | None = None

    @contextmanager
    def start(self):
        """
        Start a transactional Unit of Work.

        Yields:
            self: UnitOfWork instance with initialized storage repositories

        Raises:
            Exception: Any exception from storage operations (triggers rollback)
        """
        self.session = SessionLocal()
        try:
            self.naive_rag_storage = ORMNaiveRagStorage(session=self.session)
            self.graph_rag_storage = ORMGraphRagStorage(session=self.session)

            yield self

            self.session.commit()
        except Exception as e:
            self.session.rollback()
            raise e
        finally:
            self.session.close()
            self.session = None
