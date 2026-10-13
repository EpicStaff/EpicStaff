import pytest
from utils.singleton_meta import SingletonMeta
from infrastructure.persistence.connection_repository import ConnectionRepository
from src.shared.models import RealtimeAgentChatData


@pytest.fixture(autouse=True)
def reset_singleton():
    """Each test gets a fresh ConnectionRepository; other singletons are left alone."""
    SingletonMeta._instances.pop(ConnectionRepository, None)
    yield
    SingletonMeta._instances.pop(ConnectionRepository, None)


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


@pytest.fixture
def repo():
    return ConnectionRepository(max_connections=2, ttl_seconds=5)


def test_saved_connection_is_found_until_it_is_used(repo):
    """Single-use: once a session attached with the key, it must not resolve again."""
    first, replacement = _make_data("k"), _make_data("k")
    repo.save_connection("k", first)
    repo.save_connection("k", replacement)

    assert repo.get_connection("k") is replacement
    repo.delete_connection("k")
    repo.delete_connection("never-existed")
    assert repo.get_connection("k") is None


def test_the_oldest_connection_is_evicted_at_capacity(repo):
    for key in ("a", "b", "c"):
        repo.save_connection(key, _make_data(key))

    assert [repo.get_connection(key) is not None for key in ("a", "b", "c")] == [False, True, True]


@pytest.mark.parametrize(("elapsed", "found"), [(4.9, True), (5.0, False)])
def test_an_unused_connection_key_expires(repo, monkeypatch, elapsed, found):
    """Otherwise a leaked or guessed key would stay a valid credential forever."""
    import infrastructure.persistence.connection_repository as repo_module

    clock = {"now": 1000.0}
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: clock["now"])
    repo.save_connection("key1", _make_data("key1"))

    clock["now"] += elapsed

    assert (repo.get_connection("key1") is not None) is found
