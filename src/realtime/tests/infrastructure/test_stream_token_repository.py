"""Stream tokens: short-lived, single-use, bound to one channel, capped per channel."""

import pytest

import infrastructure.persistence.stream_token_repository as repo_module
from infrastructure.persistence.stream_token_repository import StreamTokenRepository
from utils.singleton_meta import SingletonMeta


def _fresh_repository(monkeypatch, **kwargs) -> StreamTokenRepository:
    """A new store for this test; the previously registered singleton is restored after it."""
    monkeypatch.delitem(SingletonMeta._instances, StreamTokenRepository, raising=False)
    repository = StreamTokenRepository(**kwargs)
    # Recorded after the delitem, so teardown unregisters this instance before the
    # delitem's undo puts back whatever was registered before.
    monkeypatch.setitem(SingletonMeta._instances, StreamTokenRepository, repository)
    return repository


@pytest.fixture
def fake_clock(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: clock["now"])
    return clock


@pytest.fixture
def repo(monkeypatch):
    return _fresh_repository(monkeypatch, ttl_seconds=5, max_tokens_per_key=2)


@pytest.mark.parametrize(
    ("minted_for", "presented", "consumed_for", "accepted"),
    [
        ("chan-1", "minted", "chan-1", True),
        # A token for one channel must not open another channel's stream.
        ("chan-1", "minted", "chan-2", False),
        ("chan-1", None, "chan-1", False),
        ("chan-1", "never-minted", "chan-1", False),
    ],
    ids=["matching-channel", "other-channel", "no-token", "unknown-token"],
)
def test_token_opens_only_the_stream_it_was_minted_for(repo, minted_for, presented, consumed_for, accepted):
    token = repo.mint(bound_key=minted_for)

    assert repo.consume(token if presented == "minted" else presented, bound_key=consumed_for) is accepted


@pytest.mark.parametrize("first_bound_key", ["chan-1", "wrong"], ids=["after-use", "after-failed-attempt"])
def test_token_is_burned_by_the_first_attempt(repo, first_bound_key):
    """Replay protection; a failed attempt burns it too, so mismatches can't be probed."""
    token = repo.mint(bound_key="chan-1")
    repo.consume(token, bound_key=first_bound_key)

    assert repo.consume(token, bound_key="chan-1") is False


@pytest.mark.parametrize(("elapsed", "accepted"), [(4.9, True), (5.0, False)])
def test_token_expires_after_its_ttl(repo, fake_clock, elapsed, accepted):
    token = repo.mint(bound_key="chan-1")

    fake_clock["now"] += elapsed

    assert repo.consume(token, bound_key="chan-1") is accepted


def test_a_channel_at_its_cap_evicts_its_own_oldest_token_never_another_channels(repo):
    other_channels_token = repo.mint(bound_key="chan-2")
    oldest, middle, newest = (repo.mint(bound_key="chan-1") for _ in range(3))

    assert repo.consume(other_channels_token, bound_key="chan-2") is True
    assert repo.consume(oldest, bound_key="chan-1") is False
    assert repo.consume(middle, bound_key="chan-1") is True
    assert repo.consume(newest, bound_key="chan-1") is True


def test_a_consumed_token_frees_its_channels_slot(repo):
    consumed = repo.mint(bound_key="chan-1")
    kept = repo.mint(bound_key="chan-1")
    repo.consume(consumed, bound_key="chan-1")

    newest = repo.mint(bound_key="chan-1")

    assert repo.consume(kept, bound_key="chan-1") is True
    assert repo.consume(newest, bound_key="chan-1") is True


@pytest.fixture
def single_slot_repo(monkeypatch):
    return _fresh_repository(monkeypatch, ttl_seconds=5, max_tokens_per_key=1)


def test_minting_after_a_pending_token_expired_frees_its_channels_slot(single_slot_repo, fake_clock):
    expired = single_slot_repo.mint(bound_key="chan-1")
    fake_clock["now"] += 5

    fresh = single_slot_repo.mint(bound_key="chan-1")

    assert single_slot_repo.consume(fresh, bound_key="chan-1") is True
    assert single_slot_repo.consume(expired, bound_key="chan-1") is False


def test_consuming_an_expired_token_frees_its_channels_slot(single_slot_repo, fake_clock):
    expired = single_slot_repo.mint(bound_key="chan-1")
    fake_clock["now"] += 5
    assert single_slot_repo.consume(expired, bound_key="chan-1") is False

    fresh = single_slot_repo.mint(bound_key="chan-1")

    assert single_slot_repo.consume(fresh, bound_key="chan-1") is True
