import os

# app.core.settings requires these at import time - see tests/test_export_routes.py.
os.environ.setdefault("OPENSEARCH_PASSWORD", "test")
os.environ.setdefault("AUDITOR_INGEST_API_KEY", "test-ingest-key")
os.environ.setdefault("AUDIT_JWT_SECRET", "test-secret")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "")
os.environ.setdefault("AUDITOR_REDIS_DB", "1")

import pytest
from opensearchpy.exceptions import RequestError

from app.domains.sessions.index import SESSIONS_INDEX
from app.index_setup.runner import ensure_index


class _FakeIndices:
    def __init__(self, *, exists: bool, create_error: Exception | None = None):
        self._exists = exists
        self._create_error = create_error
        self.created: list[str] = []

    async def exists(self, index: str) -> bool:
        return self._exists

    async def create(self, index: str, body: dict) -> dict:
        if self._create_error is not None:
            raise self._create_error
        self.created.append(index)
        return {"acknowledged": True}


class _FakeClient:
    def __init__(self, indices: _FakeIndices):
        self.indices = indices


@pytest.mark.asyncio
async def test_ensure_index_creates_missing_index():
    indices = _FakeIndices(exists=False)

    await ensure_index(_FakeClient(indices), SESSIONS_INDEX)

    assert indices.created == [SESSIONS_INDEX.name]


@pytest.mark.asyncio
async def test_ensure_index_skips_existing_index():
    indices = _FakeIndices(exists=True)

    await ensure_index(_FakeClient(indices), SESSIONS_INDEX)

    assert indices.created == []


@pytest.mark.asyncio
async def test_ensure_index_treats_losing_the_creation_race_as_success():
    already_exists = RequestError(
        400,
        "resource_already_exists_exception",
        {"error": {"type": "resource_already_exists_exception"}, "status": 400},
    )
    indices = _FakeIndices(exists=False, create_error=already_exists)

    await ensure_index(_FakeClient(indices), SESSIONS_INDEX)


@pytest.mark.asyncio
async def test_ensure_index_propagates_other_creation_errors():
    bad_mapping = RequestError(
        400,
        "mapper_parsing_exception",
        {"error": {"type": "mapper_parsing_exception"}, "status": 400},
    )
    indices = _FakeIndices(exists=False, create_error=bad_mapping)

    with pytest.raises(RequestError):
        await ensure_index(_FakeClient(indices), SESSIONS_INDEX)
