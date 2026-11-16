"""Restoring a version caps the grants it brings to what the restoring user may hand out."""

import pytest

from rbac.models.enums import Permission, ResourceType
from tables.graph_versioning.services import GraphVersioningService
from tables.models import Graph, PythonCode
from tables.models.graph_models import PythonNode, StartNode
from tables.services.storage_grants.errors import StorageGrantDeniedError
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

GRANT_KEYS = ("storage_grant_read", "storage_grant_write", "storage_grant_delete")


def _flags(read, write, delete):
    return dict(zip(GRANT_KEYS, (read, write, delete), strict=True))


def _stored_flags(graph):
    node = PythonNode.objects.get(graph=graph)
    return tuple(getattr(node, key) for key in GRANT_KEYS)


@pytest.fixture
def flow(acme):
    graph = Graph.objects.create(name="restore-grants", org=acme)
    StartNode.objects.create(graph=graph, variables={})
    PythonNode.objects.create(
        graph=graph,
        python_code=PythonCode.objects.create(code="def main(): return 1", entrypoint="main"),
        **_flags(True, True, False),
    )
    return graph


@pytest.fixture
def pre_grant_version(flow):
    """A version saved before grants existed: its python node carries no grant keys."""
    version = GraphVersioningService().save_version(graph=flow, name="pre-grant")
    for node in version.snapshot["nodes"]:
        for key in GRANT_KEYS:
            node.pop(key, None)
    version.save(update_fields=["snapshot"])
    return version


def _restore(version, user):
    version.graph.refresh_from_db()
    return GraphVersioningService().restore_version(
        version, expected_save_version=version.graph.save_version, user=user
    )


@pytest.mark.django_db
def test_member_restores_pre_grant_snapshot(flow, pre_grant_version, member_only):
    result = _restore(pre_grant_version, member_only)

    assert result["restored"] is True
    assert _stored_flags(flow) == (True, True, False)


@pytest.mark.django_db
def test_org_admin_restoring_a_pre_grant_snapshot_gets_every_box_ticked(
    flow, pre_grant_version, admin_acme
):
    _restore(pre_grant_version, admin_acme)

    assert _stored_flags(flow) == (True, True, True)


@pytest.mark.django_db
def test_restoring_a_snapshot_never_grants_more_than_the_user_holds(
    flow, acme, custom_role_user
):
    version = GraphVersioningService().save_version(graph=flow, name="rw")
    for node in version.snapshot["nodes"]:
        if "storage_grant_delete" in node:
            node.update(_flags(True, True, True))
    version.save(update_fields=["snapshot"])
    reader = custom_role_user(
        acme,
        "restore-reader@example.com",
        {
            ResourceType.FLOWS: Permission.READ | Permission.UPDATE,
            ResourceType.FILES: Permission.READ | Permission.CREATE | Permission.UPDATE,
        },
    )

    _restore(version, reader)

    assert _stored_flags(flow) == (True, True, False)


@pytest.mark.django_db
def test_restoring_over_a_node_with_delete_ticked_is_refused_for_a_member(
    flow, pre_grant_version, member_only
):
    PythonNode.objects.filter(graph=flow).update(**_flags(True, True, True))

    with pytest.raises(StorageGrantDeniedError):
        _restore(pre_grant_version, member_only)

    assert _stored_flags(flow) == (True, True, True)


@pytest.fixture
def old_version_with_switch(flow):
    """A version saved while the storage switch existed: the node carries it next to ticked boxes."""

    def _make(switch):
        version = GraphVersioningService().save_version(graph=flow, name="with-switch")
        for node in version.snapshot["nodes"]:
            if "storage_grant_delete" in node:
                node.update(_flags(True, True, True))
                if switch is not None:
                    node["use_storage"] = switch
        version.save(update_fields=["snapshot"])
        return version

    return _make


@pytest.mark.django_db
def test_restoring_a_snapshot_whose_switch_was_off_leaves_every_box_off(
    flow, old_version_with_switch, admin_acme
):
    _restore(old_version_with_switch(False), admin_acme)

    assert _stored_flags(flow) == (False, False, False)


@pytest.mark.django_db
@pytest.mark.parametrize("switch", [True, None])
def test_restoring_a_snapshot_whose_switch_was_on_or_missing_keeps_its_boxes(
    flow, old_version_with_switch, admin_acme, switch
):
    _restore(old_version_with_switch(switch), admin_acme)

    assert _stored_flags(flow) == (True, True, True)
