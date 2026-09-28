from unittest.mock import patch

import pytest
from tables.models.base_models import DefaultBaseModel
from tables.models.default_models import DefaultModels

# `DefaultBaseModel._load_cache` is cleared before/after every test by the
# repo-wide autouse fixture in tests/conftest.py -- no file-local fixture
# needed here.


@pytest.mark.django_db
def test_load_serves_the_cached_instance_within_the_ttl():
    """A second load() within the TTL window does not hit the database again."""
    first = DefaultModels.load()
    with patch.object(DefaultModels.objects, "get_or_create") as mock_get_or_create:
        second = DefaultModels.load()
    assert second is first
    mock_get_or_create.assert_not_called()


@pytest.mark.django_db
def test_load_refetches_once_the_cache_entry_is_older_than_the_ttl():
    """After the TTL elapses, load() re-fetches from the database and re-primes the cache with a fresh timestamp."""
    first = DefaultModels.load()
    first_cached_at = DefaultBaseModel._load_cache[DefaultModels][1]

    # load() calls time.monotonic() twice when the cache is stale: once for
    # the TTL-elapsed check, once more to stamp the re-cached entry. Feeding
    # both calls the SAME mocked value would make this test unable to tell
    # "re-primed with a fresh timestamp" apart from "left the stale timestamp
    # in place" -- side_effect gives each call a distinct, ordered value.
    future = first_cached_at + DefaultModels._CACHE_TTL_SECONDS + 100
    later = future + 1
    with patch("tables.models.base_models.time.monotonic", side_effect=[future, later]):
        refetched = DefaultModels.load()

    assert refetched.pk == 1
    second_cached_at = DefaultBaseModel._load_cache[DefaultModels][1]
    assert second_cached_at == later
    assert second_cached_at != first_cached_at

    # A subsequent load(), using the real clock, must not hit the DB again --
    # `later` is far enough in the future that the real clock won't have
    # caught up to it, so this call should still be served from cache.
    with patch.object(DefaultModels.objects, "get_or_create") as mock_get_or_create:
        DefaultModels.load()
    mock_get_or_create.assert_not_called()
