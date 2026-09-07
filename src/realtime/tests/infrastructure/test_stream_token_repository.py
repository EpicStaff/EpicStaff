import pytest
from utils.singleton_meta import SingletonMeta
from infrastructure.persistence.stream_token_repository import StreamTokenRepository


@pytest.fixture(autouse=True)
def reset_singleton():
    """Each test gets a fresh StreamTokenRepository instance."""
    SingletonMeta._instances.clear()
    yield
    SingletonMeta._instances.clear()


def test_mint_returns_token_string():
    repo = StreamTokenRepository()
    token = repo.mint(bound_key="chan-1")
    assert isinstance(token, str)
    assert token


def test_mint_returns_unique_tokens():
    repo = StreamTokenRepository()
    assert repo.mint(bound_key="chan-1") != repo.mint(bound_key="chan-1")


def test_consume_valid_token_with_matching_bound_key():
    repo = StreamTokenRepository()
    token = repo.mint(bound_key="chan-1")
    assert repo.consume(token, bound_key="chan-1") is True


def test_consume_rejects_wrong_bound_key():
    """A token minted for one channel must not validate a stream WS for a
    different channel (or the legacy route)."""
    repo = StreamTokenRepository()
    token = repo.mint(bound_key="chan-1")
    assert repo.consume(token, bound_key="chan-2") is False


def test_consume_none_token_rejected():
    repo = StreamTokenRepository()
    assert repo.consume(None, bound_key="chan-1") is False


def test_consume_unknown_token_rejected():
    repo = StreamTokenRepository()
    assert repo.consume("never-minted", bound_key="chan-1") is False


# ---------------------------------------------------------------------------
# Single-use
# ---------------------------------------------------------------------------


def test_token_is_single_use():
    repo = StreamTokenRepository()
    token = repo.mint(bound_key="chan-1")
    assert repo.consume(token, bound_key="chan-1") is True
    # Second attempt with the exact same token must fail — replay protection.
    assert repo.consume(token, bound_key="chan-1") is False


def test_failed_bound_key_match_still_invalidates_token():
    """Even a failed validation attempt (wrong bound_key) burns the token —
    an attacker can't use mismatches to probe repeatedly."""
    repo = StreamTokenRepository()
    token = repo.mint(bound_key="chan-1")
    assert repo.consume(token, bound_key="wrong") is False
    assert repo.consume(token, bound_key="chan-1") is False


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def test_token_expires_after_ttl(monkeypatch):
    import infrastructure.persistence.stream_token_repository as repo_module

    fake_time = {"now": 1000.0}
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: fake_time["now"])

    repo = StreamTokenRepository(ttl_seconds=5)
    token = repo.mint(bound_key="chan-1")

    fake_time["now"] += 5.1
    assert repo.consume(token, bound_key="chan-1") is False


def test_token_not_yet_expired_within_ttl(monkeypatch):
    import infrastructure.persistence.stream_token_repository as repo_module

    fake_time = {"now": 1000.0}
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: fake_time["now"])

    repo = StreamTokenRepository(ttl_seconds=120)
    token = repo.mint(bound_key="chan-1")

    fake_time["now"] += 119.0
    assert repo.consume(token, bound_key="chan-1") is True


# ---------------------------------------------------------------------------
# Capacity eviction
# ---------------------------------------------------------------------------


def test_capacity_evicts_oldest_token():
    repo = StreamTokenRepository(max_tokens=2)
    t1 = repo.mint(bound_key="chan-1")
    repo.mint(bound_key="chan-2")
    repo.mint(bound_key="chan-3")
    # t1 was the oldest and should have been evicted.
    assert repo.consume(t1, bound_key="chan-1") is False


def test_mint_lost_after_repository_reinstantiation_simulating_process_restart():
    """Reproduces the live-regression failure mode: the TwiML webhook mints a
    token in one `StreamTokenRepository` instance, but if that process is
    replaced before the paired WebSocket connects (e.g. an uvicorn `--reload`
    restart, or — architecturally identical — a second worker process that
    never saw the mint), the *new* instance's store is empty and a 100%
    legitimate, first-and-only connection attempt is rejected as if the token
    were missing. This is not a token-store logic bug (see all tests above,
    which pass); it's the in-process-singleton design being incompatible with
    anything that replaces the process between mint and consume."""
    minting_process_repo = StreamTokenRepository()
    token = minting_process_repo.mint(bound_key="chan-1")

    # Simulate the process boundary: a fresh StreamTokenRepository instance,
    # as would exist in a newly-spawned worker (reload restart, or a second
    # concurrent process) that never received the mint.
    SingletonMeta._instances.clear()
    consuming_process_repo = StreamTokenRepository()

    assert consuming_process_repo is not minting_process_repo
    assert consuming_process_repo.consume(token, bound_key="chan-1") is False


def test_legacy_and_channel_tokens_are_not_interchangeable():
    """The legacy `/voice/stream` sentinel bound_key must never validate a
    channel-token stream WS, and a channel token must never validate the
    legacy route."""
    repo = StreamTokenRepository()
    legacy_token = repo.mint(bound_key="__legacy_voice_stream__")
    channel_token = repo.mint(bound_key="chan-1")

    assert repo.consume(legacy_token, bound_key="chan-1") is False
    assert repo.consume(channel_token, bound_key="__legacy_voice_stream__") is False
