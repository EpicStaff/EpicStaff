from contextlib import contextmanager
import os
import sys

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, Session

from storage import ORMNaiveRagStorage, ORMGraphRagStorage


def get_required_env_var(key: str) -> str:
    """
    If you see this error during local launch set all required variables in /knowledge/.env
    """
    value = os.getenv(key)
    if value is None:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


DEBUG = False
if len(sys.argv) > 1:
    if "--debug" in sys.argv:
        DEBUG = True

if DEBUG:
    load_dotenv(dotenv_path=find_dotenv("debug.env"))
else:
    load_dotenv()

# Workaround
if os.environ.get("DB_NAME"):
    DB_NAME = get_required_env_var("DB_NAME")
else:
    DB_NAME = get_required_env_var("POSTGRES_DB")

DB_USER = get_required_env_var("DB_KNOWLEDGE_USER")
DB_PASSWORD = get_required_env_var("DB_KNOWLEDGE_PASSWORD")
DB_PORT = get_required_env_var("DB_PORT")
DB_HOST = get_required_env_var("DB_HOST_NAME")

# Construct SQLAlchemy URL
DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Create engine
ENGINE = create_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)

# Scoped session
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
