"""Tests for `TunnelRegistry.resolve_unique_id`.

Regression coverage for the bug where every localhost webhook past the first
resolved to the config that registered first: `LocalhostTunnel` builds the same
`http://{host}:{port}` public URL for every localhost config that has no explicit
domain, so a domain-only lookup returned an arbitrary first match. The requested
path is the tie-breaker — a config's registered path is its `name`, which is also
the segment embedded in `unique_id` ("<provider>:<registered_path>").
"""

import pytest

from app.services.tunnel_registry import TunnelRegistry, UnregisteredWebhookPathError
from src.shared.models import LocalhostConfigData, NgrokConfigData


class _FakeTunnel:
    def __init__(self, public_url):
        self._public_url = public_url


def _registry(*entries):
    """Build a registry with a pre-populated pool of (config, public_url) pairs."""
    registry = TunnelRegistry()
    for config, public_url in entries:
        registry._tunnel_pool[config.unique_id] = (_FakeTunnel(public_url), config)
    return registry


LOCALHOST_URL = "http://localhost:8000"


async def test_localhost_configs_resolve_to_their_own_config_id():
    first = LocalhostConfigData(name="first-hook")
    second = LocalhostConfigData(name="second-hook")
    third = LocalhostConfigData(name="third-hook")
    registry = _registry(
        (first, LOCALHOST_URL), (second, LOCALHOST_URL), (third, LOCALHOST_URL)
    )

    for config in (first, second, third):
        resolved = await registry.resolve_unique_id("localhost:8000", config.name)
        assert resolved == config.unique_id


async def test_single_localhost_config_resolves_by_domain_alone():
    only = LocalhostConfigData(name="only-hook")
    registry = _registry((only, LOCALHOST_URL))

    # No path passed: a lone candidate is unambiguous.
    assert await registry.resolve_unique_id("localhost:8000") == only.unique_id


async def test_unknown_path_among_several_localhost_configs_raises():
    first = LocalhostConfigData(name="first-hook")
    second = LocalhostConfigData(name="second-hook")
    registry = _registry((first, LOCALHOST_URL), (second, LOCALHOST_URL))

    with pytest.raises(UnregisteredWebhookPathError) as excinfo:
        await registry.resolve_unique_id("localhost:8000", "not-registered")

    # Raising instead of returning is the point: no unrelated real config's id
    # can leak out as the resolution result.
    assert excinfo.value.path == "not-registered"
    assert set(excinfo.value.registered_ids) == {first.unique_id, second.unique_id}


async def test_unknown_path_with_single_localhost_config_raises():
    only = LocalhostConfigData(name="only-hook")
    registry = _registry((only, LOCALHOST_URL))

    # A lone candidate is unambiguous by domain, but that does not make every
    # path on that domain valid.
    with pytest.raises(UnregisteredWebhookPathError):
        await registry.resolve_unique_id("localhost:8000", "not-registered")


async def test_unknown_path_on_ngrok_domain_raises():
    only = NgrokConfigData(name="only-hook", auth_token="t", domain="aaa.ngrok.io")
    registry = _registry((only, "https://aaa.ngrok.io"))

    with pytest.raises(UnregisteredWebhookPathError):
        await registry.resolve_unique_id("aaa.ngrok.io", "not-registered")


async def test_ngrok_resolves_by_unique_domain():
    first = NgrokConfigData(name="first-hook", auth_token="t", domain="aaa.ngrok.io")
    second = NgrokConfigData(name="second-hook", auth_token="t", domain="bbb.ngrok.io")
    registry = _registry(
        (first, "https://aaa.ngrok.io"), (second, "https://bbb.ngrok.io")
    )

    # Unique domains: each resolves on the domain alone when no path is given.
    assert await registry.resolve_unique_id("bbb.ngrok.io") == second.unique_id
    assert (
        await registry.resolve_unique_id("aaa.ngrok.io", "first-hook")
        == first.unique_id
    )


async def test_localhost_and_ngrok_coexist():
    localhost = LocalhostConfigData(name="local-hook")
    ngrok = NgrokConfigData(name="remote-hook", auth_token="t", domain="aaa.ngrok.io")
    registry = _registry((localhost, LOCALHOST_URL), (ngrok, "https://aaa.ngrok.io"))

    assert await registry.resolve_unique_id("aaa.ngrok.io") == ngrok.unique_id
    assert (
        await registry.resolve_unique_id("localhost:8000", "local-hook")
        == localhost.unique_id
    )


@pytest.mark.parametrize("requested", ["my-hook", "/my-hook", "my-hook/"])
async def test_path_matching_ignores_surrounding_slashes(requested):
    target = LocalhostConfigData(name="my-hook")
    other = LocalhostConfigData(name="other-hook")
    registry = _registry((other, LOCALHOST_URL), (target, LOCALHOST_URL))

    assert (
        await registry.resolve_unique_id("localhost:8000", requested)
        == target.unique_id
    )


async def test_no_domain_still_resolves_a_registered_path():
    """EST-3826 path-primary fix: an empty/unrecognized Host must never gate a
    request whose path IS genuinely registered -- Host only disambiguates
    among several configs sharing one path, it is never the primary key.
    (Previously this returned None and the caller silently fell through to a
    path-only lookup downstream; now resolution itself succeeds directly.)"""
    only = LocalhostConfigData(name="only-hook")
    registry = _registry((only, LOCALHOST_URL))

    assert await registry.resolve_unique_id("", "only-hook") == only.unique_id


async def test_unknown_domain_still_resolves_a_registered_path():
    """Same fix, ngrok case: an attacker-controlled/mismatched Host must not
    block a request for a path that IS registered somewhere."""
    only = NgrokConfigData(name="only-hook", auth_token="t", domain="aaa.ngrok.io")
    registry = _registry((only, "https://aaa.ngrok.io"))

    assert await registry.resolve_unique_id("zzz.ngrok.io", "only-hook") == (
        only.unique_id
    )


async def test_domain_only_with_no_domain_still_returns_none():
    """The domain-only branch (no `path` argument at all) is unchanged: with
    nothing to key resolution on but an empty Host, there is genuinely nothing
    to resolve."""
    only = LocalhostConfigData(name="only-hook")
    registry = _registry((only, LOCALHOST_URL))

    assert await registry.resolve_unique_id("") is None


async def test_domain_only_with_unknown_domain_still_returns_none():
    only = NgrokConfigData(name="only-hook", auth_token="t", domain="aaa.ngrok.io")
    registry = _registry((only, "https://aaa.ngrok.io"))

    assert await registry.resolve_unique_id("zzz.ngrok.io") is None


async def test_path_registered_under_one_provider_resolves_regardless_of_other_hosts():
    """Path-primary in a mixed pool: an ngrok config exists on a totally
    different domain, but the localhost path requested still resolves --
    the requested path is looked up across the whole pool, not filtered down
    to whatever the Host header happens to match first."""
    ngrok = NgrokConfigData(name="other-hook", auth_token="t", domain="aaa.ngrok.io")
    local = LocalhostConfigData(name="local-hook")
    registry = _registry((ngrok, "https://aaa.ngrok.io"), (local, LOCALHOST_URL))

    assert (
        await registry.resolve_unique_id("some-unrelated-host", "local-hook")
        == local.unique_id
    )


async def test_two_configs_sharing_one_path_name_are_disambiguated_by_host():
    """Different providers CAN register the same path name -- Host is the
    tie-breaker only in this specific ambiguous case, never the primary key."""
    ngrok = NgrokConfigData(name="shared-name", auth_token="t", domain="aaa.ngrok.io")
    local = LocalhostConfigData(name="shared-name")
    registry = _registry((ngrok, "https://aaa.ngrok.io"), (local, LOCALHOST_URL))

    assert (
        await registry.resolve_unique_id("aaa.ngrok.io", "shared-name")
        == ngrok.unique_id
    )
    assert (
        await registry.resolve_unique_id("localhost:8000", "shared-name")
        == local.unique_id
    )
