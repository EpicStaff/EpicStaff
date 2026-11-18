import pytest
from graphrag_vectors.lancedb import LanceDBVectorStore
from graphrag_vectors.vector_store import VectorStoreDocument
from infrastructure.graphrag.vector_stores import S3LanceDBVectorStore

FIELDS = {"title": "str", "rank": "int", "weight": "float", "flag": "bool"}


def _store(store_class, db_path):
    store = store_class(
        db_uri=str(db_path), index_name="entities", vector_size=3, fields=dict(FIELDS)
    )
    store.connect()
    return store


@pytest.fixture
def lance_temp_dir(tmp_path, monkeypatch):
    """Where lance puts its temporary files, read from TMPDIR on every call."""
    temp_dir = tmp_path / "lance_tmp"
    temp_dir.mkdir()
    monkeypatch.setenv("TMPDIR", str(temp_dir))
    yield temp_dir


def test_create_index_leaves_no_temporary_files(tmp_path, lance_temp_dir):
    _store(S3LanceDBVectorStore, tmp_path / "ours").create_index()

    assert list(lance_temp_dir.iterdir()) == []


def test_create_index_makes_the_same_empty_table_as_graphrag(tmp_path, lance_temp_dir):
    our_store = _store(S3LanceDBVectorStore, tmp_path / "ours")
    graphrag_store = _store(LanceDBVectorStore, tmp_path / "graphrag")

    our_store.create_index()
    graphrag_store.create_index()

    assert our_store.document_collection.schema == graphrag_store.document_collection.schema
    assert our_store.document_collection.count_rows() == 0
    # graphrag's placeholder IVF_FLAT index survives the placeholder's deletion since lancedb
    # 0.41: one centroid trained on a zero vector, and every later row lands unindexed. Ours
    # has no index at all, so search is an exact scan either way.
    assert our_store.document_collection.list_indices() == []


def test_documents_loaded_after_create_index_are_found(tmp_path, lance_temp_dir):
    store = _store(S3LanceDBVectorStore, tmp_path / "ours")
    store.create_index()

    store.load_documents(
        [
            VectorStoreDocument(id="near", vector=[1.0, 0.0, 0.0], data={"title": "a"}),
            VectorStoreDocument(id="far", vector=[0.0, 0.0, 1.0], data={"title": "b"}),
        ]
    )

    results = store.similarity_search_by_vector([0.9, 0.1, 0.0], k=1)
    assert [result.document.id for result in results] == ["near"]
