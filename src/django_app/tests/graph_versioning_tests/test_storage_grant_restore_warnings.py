"""A restore tells the user which ticked storage boxes it unticked for lack of permission."""

import pytest

from rbac.models.enums import Permission, ResourceType
from tables.graph_versioning.services import GraphVersioningService
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    PythonNode,
    StartNode,
)
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

GRANT_KEYS = ("storage_grant_read", "storage_grant_write", "storage_grant_delete")


def _flags(read, write, delete):
    return dict(zip(GRANT_KEYS, (read, write, delete), strict=True))


@pytest.fixture
def flow(acme):
    graph = Graph.objects.create(name="restore-warnings", org=acme)
    StartNode.objects.create(graph=graph, variables={})
    PythonNode.objects.create(
        graph=graph,
        node_name="py",
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


def _version_with_python_flags(flow, **extra):
    version = GraphVersioningService().save_version(graph=flow, name="flags")
    for node in version.snapshot["nodes"]:
        if "storage_grant_delete" in node:
            node.update(_flags(True, True, True))
            node.update(extra)
    version.save(update_fields=["snapshot"])
    return version


def _restore(version, user):
    version.graph.refresh_from_db()
    return GraphVersioningService().restore_version(
        version, expected_save_version=version.graph.save_version, user=user
    )


def _capped(result):
    return [w for w in result["warnings"] if w["type"] == "storage_grant_capped"]


@pytest.mark.django_db
def test_restore_warns_which_ticked_box_a_member_lost(flow, member_only):
    version = _version_with_python_flags(flow)

    result = _restore(version, member_only)

    restored = PythonNode.objects.get(graph=flow)
    assert _capped(result) == [
        {
            "type": "storage_grant_capped",
            "node_name": "py",
            "node_type": "PythonNode",
            "node_id": restored.id,
            "field": "python_code",
            "dropped_grants": ["delete"],
            "missing_permissions": ["Files: Delete"],
        }
    ]


@pytest.mark.django_db
def test_a_pre_grant_snapshot_warns_a_member_about_delete(flow, pre_grant_version, member_only):
    (warning,) = _capped(_restore(pre_grant_version, member_only))

    assert warning["dropped_grants"] == ["delete"]
    assert warning["missing_permissions"] == ["Files: Delete"]


@pytest.mark.django_db
def test_a_user_holding_every_permission_gets_no_such_warning(flow, pre_grant_version, admin_acme):
    assert _capped(_restore(pre_grant_version, admin_acme)) == []


@pytest.mark.django_db
def test_a_box_turned_off_by_the_retired_switch_is_not_reported(flow, member_only):
    version = _version_with_python_flags(flow, use_storage=False)

    assert _capped(_restore(version, member_only)) == []


@pytest.mark.django_db
def test_a_missing_update_permission_is_what_a_dropped_write_box_names(
    flow, acme, custom_role_user
):
    version = _version_with_python_flags(flow)
    PythonNode.objects.filter(graph=flow).update(**_flags(True, False, False))
    creator_without_update = custom_role_user(
        acme,
        "restore-no-update@example.com",
        {
            ResourceType.FLOWS: Permission.READ | Permission.UPDATE,
            ResourceType.FILES: Permission.READ | Permission.CREATE | Permission.DELETE,
        },
    )

    (warning,) = _capped(_restore(version, creator_without_update))

    assert warning["dropped_grants"] == ["write"]
    assert warning["missing_permissions"] == ["Files: Update"]


@pytest.mark.django_db
def test_a_classification_slot_is_reported_under_its_own_code_field(acme, member_only):
    graph = Graph.objects.create(name="restore-cdt-warnings", org=acme)
    StartNode.objects.create(graph=graph, variables={})
    ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name="cdt",
        post_python_code=PythonCode.objects.create(code="def main(): return 1", entrypoint="main"),
        post_storage_grant_delete=True,
    )
    version = GraphVersioningService().save_version(graph=graph, name="cdt")
    ClassificationDecisionTableNode.objects.filter(graph=graph).update(
        post_storage_grant_delete=False
    )

    (warning,) = _capped(_restore(version, member_only))

    assert warning["node_type"] == "ClassificationDecisionTableNode"
    assert warning["node_name"] == "cdt"
    assert warning["field"] == "post_python_code"
    assert warning["dropped_grants"] == ["delete"]


@pytest.mark.django_db
def test_preview_writes_nothing_and_reports_no_capped_grants(flow, pre_grant_version, member_only):
    preview = GraphVersioningService().preview_version(pre_grant_version, user=member_only)

    assert [w for w in preview["warnings"] if w["type"] == "storage_grant_capped"] == []


@pytest.mark.django_db
def test_creating_a_flow_from_a_version_reports_the_capped_boxes_too(
    flow, pre_grant_version, member_only
):
    result = GraphVersioningService().create_graph_from_version(pre_grant_version, user=member_only)

    (warning,) = _capped(result)
    assert warning["dropped_grants"] == ["delete"]
    assert warning["node_id"] == PythonNode.objects.get(graph_id=result["graph_id"]).id
