"""A grant's purge error stays until a whole pass gets through every row: a pass its deadline cut
short may never have reached the row that failed."""

import time

import pytest
from django.core.cache import cache
from plugins.lifecycle.grant_purge_service import GrantPurgeService
from plugins.models import GrantState, PluginGrant, PluginOwnedResource
from plugins.ownership.owned_resource_purger import FAILED_ROW_CACHE_KEY

from tests.plugins_tests.suspension_helpers import own, secret_row

pytestmark = pytest.mark.django_db

ERROR = "Secret 9: RuntimeError"


@pytest.fixture(autouse=True)
def no_failed_rows():
    cache.delete_pattern("plugins:purge:failed:*")
    yield
    cache.delete_pattern("plugins:purge:failed:*")


@pytest.fixture
def purging_grant(running_plugin, grant_to, acme):
    """A purging grant with three rows to delete, the last of which failed within the hour."""
    grant = grant_to(running_plugin(), acme, state=GrantState.PURGING)
    for name in ("first", "second", "third"):
        own(secret_row(acme, name), grant)
    rows = list(PluginOwnedResource.objects.filter(grant=grant).order_by("pk").values_list("pk", flat=True))
    cache.set(FAILED_ROW_CACHE_KEY.format(pk=rows[-1]), 1, 3600)
    PluginGrant.objects.filter(pk=grant.pk).update(last_purge_error=ERROR)
    grant.refresh_from_db()
    return grant


def _error_after(grant, *, seconds: float):
    result = GrantPurgeService().advance(grant, until=time.monotonic() + seconds)
    grant.refresh_from_db()
    return result, grant.last_purge_error


def test_a_pass_its_deadline_cut_short_keeps_the_error(purging_grant):
    result, error = _error_after(purging_grant, seconds=-1)

    assert (result.truncated, result.purged, result.failed) == (True, 1, 0)
    assert error == ERROR


def test_a_pass_that_held_back_the_failed_row_keeps_the_error(purging_grant):
    result, error = _error_after(purging_grant, seconds=30)

    assert (result.truncated, result.held_back, result.failed) == (False, 1, 0)
    assert error == ERROR


def test_a_whole_pass_without_a_failure_clears_the_error(purging_grant):
    cache.delete_pattern("plugins:purge:failed:*")

    result, error = _error_after(purging_grant, seconds=30)

    assert (result.truncated, result.held_back, result.failed, result.remaining) == (False, 0, 0, 0)
    assert error is None
