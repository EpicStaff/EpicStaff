"""Tests for `TunnelRegistry.resolve_by_path`.

Rewritten for the path-primary routing model (EST-3826) plus the org-aware
`unique_id` fix (EST-3862/EST-3826 follow-up, C3): `BaseTunnelConfigData.name`
is the raw `WebhookTrigger.path`, which the DB only guarantees unique
per-org (`unique_together(org, path, provider_type)`), not globally. Two
different orgs -- or two different providers -- can legitimately register the
identical path string. The inbound request carries nothing but that path, so
when more than one pool entry matches, there is no legitimate way to pick a
winner: `resolve_by_path` must fail closed via `AmbiguousWebhookPathError`
rather than silently returning an arbitrary match (which could route one
org's webhook event into another org's graph).

Covers:
  - Basic single-match resolution (unchanged behavior).
  - Two different orgs registering the identical path do NOT silently
    collide in the pool (distinct `unique_id`s -- both stay registered).
  - A request for that colliding path raises `AmbiguousWebhookPathError`
    (never resolves to either org's config).
  - Normal, non-colliding single-org paths still resolve exactly as before.
  - Path normalization (surrounding slashes) is unchanged.
"""

import pytest

from app.services.tunnel_registry import (
    AmbiguousWebhookPathError,
    TunnelRegistry,
    UnregisteredWebhookPathError,
)
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


async def test_single_registered_path_resolves():
    config = LocalhostConfigData(name="only-hook", org_id=1)
    registry = _registry((config, LOCALHOST_URL))

    unique_id, resolved_config = await registry.resolve_by_path("only-hook")

    assert unique_id == config.unique_id
    assert resolved_config == config


async def test_unknown_path_raises_unregistered():
    config = LocalhostConfigData(name="only-hook", org_id=1)
    registry = _registry((config, LOCALHOST_URL))

    with pytest.raises(UnregisteredWebhookPathError) as excinfo:
        await registry.resolve_by_path("not-registered")

    assert excinfo.value.path == "not-registered"
    assert excinfo.value.registered_ids == [config.unique_id]


@pytest.mark.parametrize("requested", ["my-hook", "/my-hook", "my-hook/"])
async def test_path_matching_ignores_surrounding_slashes(requested):
    target = LocalhostConfigData(name="my-hook", org_id=1)
    other = LocalhostConfigData(name="other-hook", org_id=1)
    registry = _registry((other, LOCALHOST_URL), (target, LOCALHOST_URL))

    unique_id, resolved_config = await registry.resolve_by_path(requested)

    assert unique_id == target.unique_id
    assert resolved_config == target


async def test_ngrok_and_localhost_coexist_on_distinct_paths():
    localhost = LocalhostConfigData(name="local-hook", org_id=1)
    ngrok = NgrokConfigData(
        name="remote-hook", org_id=1, auth_token="t", domain="aaa.ngrok.io"
    )
    registry = _registry((localhost, LOCALHOST_URL), (ngrok, "https://aaa.ngrok.io"))

    unique_id, resolved = await registry.resolve_by_path("local-hook")
    assert unique_id == localhost.unique_id
    assert resolved == localhost

    unique_id, resolved = await registry.resolve_by_path("remote-hook")
    assert unique_id == ngrok.unique_id
    assert resolved == ngrok


async def test_two_different_orgs_sharing_one_path_do_not_collide_in_the_pool():
    """C3 regression: org A and org B both register a `WebhookTrigger` with
    path='shared-path'. Before the fix, both configs' `unique_id` was
    `f"ngrok:shared-path"` -- identical -- so registering the second
    silently overwrote the first in `_tunnel_pool`. With `org_id` folded
    into `unique_id`, both must coexist as distinct pool entries."""
    org_a_config = NgrokConfigData(
        name="shared-path", org_id=1, auth_token="t", domain="org-a.ngrok.io"
    )
    org_b_config = NgrokConfigData(
        name="shared-path", org_id=2, auth_token="t", domain="org-b.ngrok.io"
    )

    assert org_a_config.unique_id != org_b_config.unique_id

    registry = _registry(
        (org_a_config, "https://org-a.ngrok.io"),
        (org_b_config, "https://org-b.ngrok.io"),
    )

    # Both entries genuinely coexist -- neither silently overwrote the other.
    assert len(registry._tunnel_pool) == 2
    assert org_a_config.unique_id in registry._tunnel_pool
    assert org_b_config.unique_id in registry._tunnel_pool


async def test_request_for_a_path_shared_by_two_orgs_is_rejected_ambiguous():
    """A request for 'shared-path' can never legitimately resolve to EITHER
    org's config from the path alone -- must fail closed, never guess."""
    org_a_config = NgrokConfigData(
        name="shared-path", org_id=1, auth_token="t", domain="org-a.ngrok.io"
    )
    org_b_config = NgrokConfigData(
        name="shared-path", org_id=2, auth_token="t", domain="org-b.ngrok.io"
    )
    registry = _registry(
        (org_a_config, "https://org-a.ngrok.io"),
        (org_b_config, "https://org-b.ngrok.io"),
    )

    with pytest.raises(AmbiguousWebhookPathError) as excinfo:
        await registry.resolve_by_path("shared-path")

    assert excinfo.value.path == "shared-path"
    assert set(excinfo.value.matched_ids) == {
        org_a_config.unique_id,
        org_b_config.unique_id,
    }


async def test_distinct_provider_types_sharing_one_path_string_are_also_ambiguous():
    """Not just an org problem: an ngrok config and a localhost config that
    happen to share the same `name` (path) are equally undisambiguatable
    from the request alone, and must also fail closed rather than pick
    whichever the dict iteration returns first."""
    ngrok = NgrokConfigData(
        name="shared-name", org_id=1, auth_token="t", domain="aaa.ngrok.io"
    )
    local = LocalhostConfigData(name="shared-name", org_id=1)
    registry = _registry((ngrok, "https://aaa.ngrok.io"), (local, LOCALHOST_URL))

    with pytest.raises(AmbiguousWebhookPathError) as excinfo:
        await registry.resolve_by_path("shared-name")

    assert set(excinfo.value.matched_ids) == {ngrok.unique_id, local.unique_id}


async def test_single_org_path_resolution_is_unaffected_by_the_org_fix():
    """No regression: the ordinary, non-colliding single-org case resolves
    exactly as before -- the org fix only changes behavior when there is a
    genuine collision."""
    trigger_a = NgrokConfigData(
        name="trigger-a", org_id=1, auth_token="t", domain="aaa.ngrok.io"
    )
    trigger_b = LocalhostConfigData(name="trigger-b", org_id=1)
    registry = _registry(
        (trigger_a, "https://aaa.ngrok.io"), (trigger_b, LOCALHOST_URL)
    )

    unique_id, resolved = await registry.resolve_by_path("trigger-a")
    assert unique_id == trigger_a.unique_id
    assert resolved == trigger_a

    unique_id, resolved = await registry.resolve_by_path("trigger-b")
    assert unique_id == trigger_b.unique_id
    assert resolved == trigger_b
