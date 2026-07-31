import json

import pytest

import storage as storage_module
from storage import EpicStaffStorage, clear_mutations
from fakes import FakeS3Client

TEST_BUCKET = "test-bucket"


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset process-wide state the module keeps at import time.

    ``STORAGE_ALLOWED_PATHS`` is cached in the module-level ``__cache``
    dict on first read (see ``__get_allowed_paths``), so tests that set
    the env var via ``monkeypatch.setenv`` must clear this cache first or
    the new value is silently ignored. ``__cache`` is a module-level name
    (not a class attribute), so it is not name-mangled and is reachable
    with plain attribute access from this non-class scope.

    ``_mutations`` is also module-level and must not leak between tests.
    """
    storage_module.__cache.clear()
    clear_mutations()
    yield
    storage_module.__cache.clear()
    clear_mutations()


@pytest.fixture
def fake_client() -> FakeS3Client:
    return FakeS3Client()


@pytest.fixture
def storage(monkeypatch, fake_client: FakeS3Client) -> EpicStaffStorage:
    inst = EpicStaffStorage()
    # _get_client() short-circuits and returns self._client if already set,
    # so pre-populating _client/_bucket is equivalent to monkeypatching
    # _get_client itself, without needing to fake env-var validation.
    monkeypatch.setattr(inst, "_client", fake_client)
    monkeypatch.setattr(inst, "_bucket", TEST_BUCKET)
    return inst


def allow_paths(monkeypatch, paths: list[str]) -> None:
    """Set STORAGE_ALLOWED_PATHS and clear the module-level cache so the
    new value is actually read on the next check_storage_permission call.
    """
    monkeypatch.setenv("STORAGE_ALLOWED_PATHS", json.dumps(paths))
    storage_module.__cache.clear()
