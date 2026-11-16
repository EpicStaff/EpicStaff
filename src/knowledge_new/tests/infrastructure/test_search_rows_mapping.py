from types import SimpleNamespace

import pytest

pytest.importorskip(
    "psycopg",
    reason="requires libpq; only available in the Linux/Docker image, not this Windows venv",
    exc_type=ImportError,  # psycopg is installed but fails at import time without libpq
)

from infrastructure.database.mappers.naive import search_rows_to_found_chunks  # noqa: E402


def make_row(**overrides):
    row = {
        "chunk_index": 15,
        "similarity": 0.69823,
        "text": "the purple lighthouse sings at midnight",
        "file_name": "notes.txt",
        "naive_rag_document_id": 13,
    }
    row.update(overrides)
    return SimpleNamespace(**row)


def test_found_chunk_carries_the_document_it_was_found_in():
    [chunk] = search_rows_to_found_chunks([make_row()], similarity_threshold=0.2)

    assert chunk.order == 15
    assert chunk.document_id == 13
    assert chunk.source == "notes.txt"
    assert chunk.similarity == 0.6982


def test_rows_below_the_similarity_threshold_are_dropped():
    chunks = search_rows_to_found_chunks(
        [make_row(similarity=0.9), make_row(chunk_index=3, similarity=0.1)],
        similarity_threshold=0.2,
    )

    assert [chunk.order for chunk in chunks] == [15]
