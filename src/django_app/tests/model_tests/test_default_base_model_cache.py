from unittest.mock import patch

import pytest
from tables.models.crew_models import DefaultAgentConfig

# The load cache is cleared around every test by the repo-wide autouse fixture in
# tests/conftest.py. DefaultAgentConfig stands in for every DefaultBaseModel singleton.

TTL = DefaultAgentConfig._CACHE_TTL_SECONDS
CLOCK = "tables.models.base_models.time.monotonic"


@pytest.mark.django_db
def test_load_serves_the_cached_defaults_until_the_ttl_elapses():
    with patch(CLOCK, return_value=1000.0):
        DefaultAgentConfig.load()
    DefaultAgentConfig.objects.filter(pk=1).update(max_iter=7)

    with patch(CLOCK, return_value=1000.0 + TTL - 1):
        within_ttl = DefaultAgentConfig.load()
    with patch(CLOCK, return_value=1000.0 + TTL + 1):
        after_ttl = DefaultAgentConfig.load()
    # The refetch restarts the TTL from the moment it happened.
    DefaultAgentConfig.objects.filter(pk=1).update(max_iter=9)
    with patch(CLOCK, return_value=1000.0 + 2 * TTL):
        within_new_ttl = DefaultAgentConfig.load()

    assert within_ttl.max_iter == 20
    assert after_ttl.max_iter == 7
    assert within_new_ttl.max_iter == 7
