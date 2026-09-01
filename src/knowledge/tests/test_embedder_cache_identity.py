"""A changed credential must produce a new embedder.

The embedder holds the api_key and is memoised process-wide, so a cache keyed on
rag id alone would serve the first credential forever -- silently ignoring the
per-message credential this design delivers, and surviving a key rotation.
"""

from rag.naive_rag_strategy import _embedder_cache_key


def test_a_different_credential_gives_a_different_cache_key():
    assert _embedder_cache_key(naive_rag_id=2, api_key="sk-old") != _embedder_cache_key(
        naive_rag_id=2, api_key="sk-new"
    )


def test_the_same_credential_gives_the_same_cache_key():
    assert _embedder_cache_key(naive_rag_id=2, api_key="sk-a") == _embedder_cache_key(
        naive_rag_id=2, api_key="sk-a"
    )


def test_different_rags_do_not_share_a_cache_key():
    assert _embedder_cache_key(naive_rag_id=2, api_key="sk-a") != _embedder_cache_key(
        naive_rag_id=3, api_key="sk-a"
    )


def test_the_key_does_not_expose_the_credential():
    key = _embedder_cache_key(naive_rag_id=2, api_key="sk-supersecret")
    assert "sk-supersecret" not in repr(key)


def test_no_credential_is_a_stable_key():
    assert _embedder_cache_key(naive_rag_id=2, api_key=None) == _embedder_cache_key(
        naive_rag_id=2, api_key=None
    )
    assert _embedder_cache_key(naive_rag_id=2, api_key=None) != _embedder_cache_key(
        naive_rag_id=2, api_key="sk-a"
    )
