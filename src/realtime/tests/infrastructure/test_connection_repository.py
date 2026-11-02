import pytest

import infrastructure.persistence.connection_repository as repo_module
from utils.singleton_meta import SingletonMeta
from infrastructure.persistence.connection_repository import ConnectionRepository
from src.shared.models import RealtimeAgentChatData


@pytest.fixture(autouse=True)
def reset_singleton():
    """Each test gets a fresh ConnectionRepository; other singletons are left alone."""
    SingletonMeta._instances.pop(ConnectionRepository, None)
    yield
    SingletonMeta._instances.pop(ConnectionRepository, None)


def _make_data(key: str, org_id: int = 1) -> RealtimeAgentChatData:
    return RealtimeAgentChatData(
        connection_key=key,
        org_id=org_id,
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
def clock(monkeypatch):
    now = {"now": 1000.0}
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: now["now"])
    return now


@pytest.fixture
def repo():
    return ConnectionRepository(max_connections_per_org=2, max_connections=4, ttl_seconds=5)


def _pending(repo, *keys) -> list[str]:
    return [key for key in keys if repo.get_connection(key) is not None]


def test_saved_connection_is_found_until_it_is_used(repo):
    """Single-use: once a session attached with the key, it must not resolve again."""
    first, replacement = _make_data("k"), _make_data("k")
    repo.save_connection("k", first)
    repo.save_connection("k", replacement)

    assert repo.get_connection("k") is replacement
    repo.delete_connection("k")
    repo.delete_connection("never-existed")
    assert repo.get_connection("k") is None


def test_an_org_over_its_cap_loses_only_its_own_oldest_pending_key(repo):
    repo.save_connection("b1", _make_data("b1", org_id=2))
    for key in ("a1", "a2", "a3", "a4"):
        repo.save_connection(key, _make_data(key, org_id=1))

    assert _pending(repo, "b1", "a1", "a2", "a3", "a4") == ["b1", "a3", "a4"]


def test_a_key_re_saved_under_another_org_counts_only_against_that_org(repo):
    """Its first org's later burst must not evict it through a stale org bucket."""
    repo.save_connection("k", _make_data("k", org_id=1))
    repo.save_connection("k", _make_data("k", org_id=2))
    for key in ("a1", "a2"):
        repo.save_connection(key, _make_data(key, org_id=1))

    assert _pending(repo, "k", "a1", "a2") == ["k", "a1", "a2"]


def test_a_used_key_frees_its_place_in_the_org_cap(repo):
    repo.save_connection("a1", _make_data("a1"))
    repo.save_connection("a2", _make_data("a2"))
    repo.delete_connection("a1")

    repo.save_connection("a3", _make_data("a3"))
    assert _pending(repo, "a1", "a2", "a3") == ["a2", "a3"]

    # The cap is back at its limit, so the next save must evict the oldest live key.
    repo.save_connection("a4", _make_data("a4"))
    assert _pending(repo, "a2", "a3", "a4") == ["a3", "a4"]


def test_the_global_cap_evicts_the_oldest_key_of_any_org_as_a_last_resort(repo):
    for org_id, key in [(1, "a1"), (2, "b1"), (3, "c1"), (4, "d1"), (5, "e1")]:
        repo.save_connection(key, _make_data(key, org_id=org_id))

    assert _pending(repo, "a1", "b1", "c1", "d1", "e1") == ["b1", "c1", "d1", "e1"]


def test_expired_keys_are_purged_before_a_live_key_is_evicted(repo, clock, captured_log_messages):
    """Only real capacity pressure evicts, and only that is reported to operators."""
    repo.save_connection("a1", _make_data("a1", org_id=1))
    repo.save_connection("b1", _make_data("b1", org_id=2))
    clock["now"] += 1
    for org_id, key in [(1, "a2"), (3, "c1")]:
        repo.save_connection(key, _make_data(key, org_id=org_id))
    clock["now"] += 4.5  # a1 and b1 expired, a2 and c1 live; the store is at its global cap.

    repo.save_connection("a3", _make_data("a3", org_id=1))
    repo.save_connection("d1", _make_data("d1", org_id=4))

    assert _pending(repo, "a2", "c1", "a3", "d1") == ["a2", "c1", "a3", "d1"]
    assert not [message for message in captured_log_messages if "evicting" in message]


def test_saving_a_key_again_makes_it_the_newest(clock):
    """Re-saved, it expires last, so an older key expiring first is purged before it."""
    repo = ConnectionRepository(max_connections_per_org=3, max_connections=10, ttl_seconds=5)
    repo.save_connection("a1", _make_data("a1"))
    clock["now"] += 1
    repo.save_connection("a2", _make_data("a2"))
    clock["now"] += 1
    repo.save_connection("a1", _make_data("a1"))
    clock["now"] += 4.5  # a2 expired, a1 live

    repo.save_connection("a3", _make_data("a3"))
    repo.save_connection("a4", _make_data("a4"))

    assert _pending(repo, "a1", "a2", "a3", "a4") == ["a1", "a3", "a4"]


@pytest.mark.parametrize(("elapsed", "found"), [(4.9, True), (5.0, False)])
def test_an_unused_connection_key_expires(repo, clock, elapsed, found):
    """Otherwise a leaked or guessed key would stay a valid credential forever."""
    repo.save_connection("key1", _make_data("key1"))

    clock["now"] += elapsed

    assert (repo.get_connection("key1") is not None) is found
