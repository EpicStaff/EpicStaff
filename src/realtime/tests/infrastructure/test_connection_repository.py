import pytest
from unittest.mock import MagicMock
from utils.singleton_meta import SingletonMeta
from infrastructure.persistence.connection_repository import ConnectionRepository
from src.shared.models import RealtimeAgentChatData


@pytest.fixture(autouse=True)
def reset_singleton():
    """Each test gets a fresh ConnectionRepository instance."""
    SingletonMeta._instances.clear()
    yield
    SingletonMeta._instances.clear()


def _make_data(key: str) -> RealtimeAgentChatData:
    return RealtimeAgentChatData(
        connection_key=key,
        org_id=1,
        rt_api_key="k",
        rt_model_name="m",
        wake_word="",
        voice="alloy",
        temperature=0.5,
        language="en",
        goal="g",
        backstory="b",
        role="r",
        transcript_api_key="",
        transcript_model_name="",
        voice_recognition_prompt="",
        knowledge_collection_id=None,
        similarity_threshold=0.5,
        memory=False,
        stop_prompt="",
        tools=[],
        python_code_tools=[],
    )


def test_save_and_get():
    repo = ConnectionRepository()
    data = _make_data("key1")
    repo.save_connection("key1", data)
    assert repo.get_connection("key1") is data


def test_get_nonexistent_returns_none():
    repo = ConnectionRepository()
    assert repo.get_connection("missing") is None


def test_delete_connection():
    repo = ConnectionRepository()
    data = _make_data("key1")
    repo.save_connection("key1", data)
    repo.delete_connection("key1")
    assert repo.get_connection("key1") is None


def test_delete_nonexistent_is_safe():
    repo = ConnectionRepository()
    repo.delete_connection("never_existed")  # must not raise


def test_capacity_evicts_oldest():
    repo = ConnectionRepository(max_connections=3)
    for i in range(4):
        repo.save_connection(f"key{i}", _make_data(f"key{i}"))
    # key0 should be evicted (oldest)
    assert repo.get_connection("key0") is None
    assert repo.get_connection("key3") is not None


def test_capacity_keeps_newest(  ):
    repo = ConnectionRepository(max_connections=2)
    repo.save_connection("a", _make_data("a"))
    repo.save_connection("b", _make_data("b"))
    repo.save_connection("c", _make_data("c"))
    assert repo.get_connection("b") is not None
    assert repo.get_connection("c") is not None


def test_get_all_connections_returns_list():
    repo = ConnectionRepository()
    repo.save_connection("x", _make_data("x"))
    repo.save_connection("y", _make_data("y"))
    all_conns = repo.get_all_connections()
    assert len(all_conns) == 2


def test_get_all_connections_empty():
    repo = ConnectionRepository()
    assert repo.get_all_connections() == []


def test_overwrite_existing_key():
    repo = ConnectionRepository()
    data1 = _make_data("k")
    data2 = _make_data("k")
    repo.save_connection("k", data1)
    repo.save_connection("k", data2)
    assert repo.get_connection("k") is data2
    assert len(repo.get_all_connections()) == 1


# ---------------------------------------------------------------------------
# EST-1869 security fix: TTL + single-use.
# ---------------------------------------------------------------------------


def test_connection_expires_after_ttl(monkeypatch):
    """A connection_key must stop working shortly after being published if
    nobody ever connects with it — otherwise a leaked/guessed key stays a
    valid, reusable credential forever."""
    import infrastructure.persistence.connection_repository as repo_module

    fake_time = {"now": 1000.0}
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: fake_time["now"])

    repo = ConnectionRepository(ttl_seconds=5)
    repo.save_connection("key1", _make_data("key1"))
    assert repo.get_connection("key1") is not None

    fake_time["now"] += 5.1
    assert repo.get_connection("key1") is None


def test_connection_not_yet_expired_within_ttl(monkeypatch):
    import infrastructure.persistence.connection_repository as repo_module

    fake_time = {"now": 1000.0}
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: fake_time["now"])

    repo = ConnectionRepository(ttl_seconds=300)
    repo.save_connection("key1", _make_data("key1"))

    fake_time["now"] += 299.0
    assert repo.get_connection("key1") is not None


def test_delete_connection_prevents_reuse():
    """Single-use: once consumed (deleted), the same connection_key must not
    resolve to the same session data again."""
    repo = ConnectionRepository()
    repo.save_connection("key1", _make_data("key1"))
    assert repo.get_connection("key1") is not None

    repo.delete_connection("key1")

    assert repo.get_connection("key1") is None
