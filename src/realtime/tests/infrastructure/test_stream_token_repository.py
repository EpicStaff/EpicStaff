"""Stream tokens: short-lived, single-use, bound to one channel."""

import pytest

import infrastructure.persistence.stream_token_repository as repo_module
from infrastructure.persistence.stream_token_repository import StreamTokenRepository
from utils.singleton_meta import SingletonMeta

LEGACY = "__legacy_voice_stream__"


@pytest.fixture
def repo():
    # Drop only this singleton; other modules rely on theirs being shared.
    SingletonMeta._instances.pop(StreamTokenRepository, None)
    yield StreamTokenRepository(ttl_seconds=5, max_tokens=2)
    SingletonMeta._instances.pop(StreamTokenRepository, None)


@pytest.mark.parametrize(
    ("minted_for", "presented", "consumed_for", "accepted"),
    [
        ("chan-1", "minted", "chan-1", True),
        # A token for one channel must not open another channel's stream...
        ("chan-1", "minted", "chan-2", False),
        # ...nor cross between the legacy route and a channel route.
        (LEGACY, "minted", "chan-1", False),
        ("chan-1", "minted", LEGACY, False),
        ("chan-1", None, "chan-1", False),
        ("chan-1", "never-minted", "chan-1", False),
    ],
    ids=["matching-channel", "other-channel", "legacy-to-channel", "channel-to-legacy", "no-token", "unknown-token"],
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
def test_token_expires_after_its_ttl(repo, monkeypatch, elapsed, accepted):
    clock = {"now": 1000.0}
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: clock["now"])
    token = repo.mint(bound_key="chan-1")

    clock["now"] += elapsed

    assert repo.consume(token, bound_key="chan-1") is accepted


def test_the_oldest_token_is_evicted_at_capacity(repo):
    oldest = repo.mint(bound_key="chan-1")
    kept = repo.mint(bound_key="chan-2")
    repo.mint(bound_key="chan-3")

    assert repo.consume(oldest, bound_key="chan-1") is False
    assert repo.consume(kept, bound_key="chan-2") is True
