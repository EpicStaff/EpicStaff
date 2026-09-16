"""Invariants for the permission recommendation map.

These are the reason the map lives on the backend: a hand-maintained list of
`(resource, action)` pairs drifts silently from the catalog, and nothing on the
frontend can catch it.
"""

import pytest

from tables.services.rbac.permission_catalog import (
    RECOMMENDED_WITH,
    RESOURCE_TYPE_METADATA,
    build_catalog,
    recommended_with_for,
)

GRANTABLE = {
    (entry["code"], action)
    for entry in RESOURCE_TYPE_METADATA
    for action in entry["applicable_actions"]
}


def _rules():
    for resource, by_action in RECOMMENDED_WITH.items():
        for action, targets in by_action.items():
            yield (resource, action), targets


def test_every_key_is_a_grantable_pair():
    for pair, _ in _rules():
        assert pair in GRANTABLE, f"{pair[0]}:{pair[1]} is not a grantable permission"


def test_every_target_is_a_grantable_pair():
    for pair, targets in _rules():
        for target in targets:
            assert target in GRANTABLE, (
                f"{pair[0]}:{pair[1]} recommends {target[0]}:{target[1]}, "
                "which is not a grantable permission"
            )


def test_no_permission_recommends_itself():
    for pair, targets in _rules():
        assert pair not in targets, f"{pair[0]}:{pair[1]} recommends itself"


def test_no_duplicate_targets():
    for pair, targets in _rules():
        assert len(targets) == len(
            set(targets)
        ), f"{pair[0]}:{pair[1]} lists a target twice"


def test_every_grantable_pair_has_an_entry():
    for resource, action in sorted(GRANTABLE):
        assert action in recommended_with_for(
            resource
        ), f"{resource}:{action} is grantable but absent from the map"


def test_platform_actions_are_never_recommended():
    platform = {
        (entry["code"], action)
        for entry in RESOURCE_TYPE_METADATA
        for action in entry["platform_actions"]
    }
    for pair, targets in _rules():
        assert pair not in platform, f"{pair[0]}:{pair[1]} is platform-only"
        assert not platform & set(
            targets
        ), f"{pair[0]}:{pair[1]} recommends a platform-only action"


@pytest.mark.parametrize("authoring_action", ["create", "update"])
def test_authoring_covers_what_read_needs(authoring_action):
    """Creating or editing a resource needs at least the context reading it
    needs. This is the invariant `flows:create` originally violated."""
    for entry in RESOURCE_TYPE_METADATA:
        resource = entry["code"]
        actions = entry["applicable_actions"]
        if authoring_action not in actions or "read" not in actions:
            continue
        by_action = RECOMMENDED_WITH.get(resource, {})
        expected = {(resource, "read"), *by_action.get("read", ())}
        actual = set(by_action.get(authoring_action, ()))
        assert expected <= actual, (
            f"{resource}:{authoring_action} is missing "
            f"{sorted(expected - actual)}, which {resource}:read recommends"
        )


def test_accessor_returns_wire_shape():
    flows = recommended_with_for("flows")
    assert flows["delete"] == [{"resource_type": "flows", "action": "read"}]
    assert flows["read"] == [
        {"resource_type": "projects", "action": "read"},
        {"resource_type": "llm_configs", "action": "read"},
    ]


def test_accessor_is_empty_for_unknown_resource():
    assert recommended_with_for("nonsense") == {}


def test_build_catalog_does_not_mutate_module_state():
    build_catalog()
    assert all("recommended_with" not in e for e in RESOURCE_TYPE_METADATA)
