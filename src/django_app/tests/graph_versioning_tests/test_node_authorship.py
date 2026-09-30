"""Graph versioning keeps each node's author and creation time across a restore."""

import json
from datetime import UTC, datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from rbac.governance.authorship import AuthorshipReleaseService
from rbac.models import OrganizationUser
from tables.import_export.constants import NODE_MAPPING_KEY
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import Graph
from tables.models.graph_models import AgentNode, GraphNote, StartNode
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

RECORDED_AT = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
UNKNOWN_USER_ID = 987654321


def _age(node, created_at=RECORDED_AT):
    type(node).objects.filter(pk=node.pk).update(created_at=created_at)
    node.refresh_from_db()
    return node


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="authored-flow", org=acme)


@pytest.fixture
def member_agent_node(flow, member_only):
    return _age(AgentNode.objects.create(graph=flow, node_name="agent", created_by=member_only))


@pytest.fixture
def unauthored_note(flow):
    return _age(GraphNote.objects.create(graph=flow, content="note"))


def _restore(service, version, user):
    version.graph.refresh_from_db()
    return service.restore_version(
        version, expected_save_version=version.graph.save_version, user=user
    )


def _only_node(queryset):
    nodes = list(queryset)
    assert len(nodes) == 1
    return nodes[0]


# ---- save_version ----


@pytest.mark.django_db
def test_save_version_records_author_and_created_at_of_every_node(
    service, flow, member_only, member_agent_node, unauthored_note
):
    version = service.save_version(flow, name="v1")

    assert version.snapshot["node_authorship"] == {
        str(member_agent_node.id): {
            "created_by": member_only.id,
            "created_at": RECORDED_AT.isoformat(),
        },
        str(unauthored_note.id): {"created_by": None, "created_at": RECORDED_AT.isoformat()},
    }


@pytest.mark.django_db
def test_graph_export_carries_no_node_authorship(service, flow, member_agent_node):
    service.save_version(flow, name="v1")

    export_data = ExportService(entity_registry).export_entities(EntityType.GRAPH, [flow.id])

    assert "node_authorship" not in json.dumps(export_data, default=str)


# ---- restore_version ----


@pytest.mark.django_db
def test_restore_keeps_recorded_author_who_is_still_an_org_member(
    service, flow, admin_acme, member_only, member_agent_node
):
    version = service.save_version(flow, name="v1")

    _restore(service, version, admin_acme)

    restored = _only_node(flow.agent_node_list.all())
    assert restored.id != member_agent_node.id
    assert restored.created_by_id == member_only.id
    assert restored.created_at == RECORDED_AT


@pytest.mark.django_db
def test_restore_keeps_member_author_when_no_real_user_restores(
    service, flow, member_only, member_agent_node
):
    version = service.save_version(flow, name="v1")

    _restore(service, version, None)

    restored = _only_node(flow.agent_node_list.all())
    assert restored.created_by_id == member_only.id
    assert restored.created_at == RECORDED_AT


@pytest.fixture
def membership_losses(acme, beta, role_member, member_only):
    """Ways `member_only` stops being a member of acme, by test id."""

    def leave_acme():
        OrganizationUser.objects.filter(user=member_only, org=acme).delete()

    def move_to_beta():
        leave_acme()
        OrganizationUser.objects.create(user=member_only, org=beta, role=role_member)

    return {"left-org": leave_acme, "member-of-another-org-only": move_to_beta}


@pytest.mark.django_db
@pytest.mark.parametrize("membership_loss", ["left-org", "member-of-another-org-only"])
def test_restore_gives_restoring_user_the_nodes_of_an_author_who_is_not_a_member(
    service, flow, admin_acme, member_agent_node, membership_losses, membership_loss
):
    version = service.save_version(flow, name="v1")
    membership_losses[membership_loss]()

    _restore(service, version, admin_acme)

    restored = _only_node(flow.agent_node_list.all())
    assert restored.created_by_id == admin_acme.id
    assert restored.created_at == RECORDED_AT


@pytest.mark.django_db
def test_restore_gives_back_recorded_authorship_to_an_author_who_rejoined_the_org(
    service, flow, acme, role_member, admin_acme, member_only, member_agent_node
):
    version = service.save_version(flow, name="v1")
    OrganizationUser.objects.filter(user=member_only, org=acme).delete()
    AuthorshipReleaseService().release(user_id=member_only.id, org_id=acme.id)
    member_agent_node.refresh_from_db()
    assert member_agent_node.created_by_id is None
    OrganizationUser.objects.create(user=member_only, org=acme, role=role_member)

    _restore(service, version, admin_acme)

    restored = _only_node(flow.agent_node_list.all())
    assert restored.created_by_id == member_only.id
    assert restored.created_at == RECORDED_AT


@pytest.mark.django_db
def test_restore_gives_restoring_user_the_nodes_of_an_unknown_recorded_author(
    service, flow, admin_acme, member_agent_node
):
    version = service.save_version(flow, name="v1")
    for entry in version.snapshot["node_authorship"].values():
        entry["created_by"] = UNKNOWN_USER_ID
    version.save(update_fields=["snapshot"])

    _restore(service, version, admin_acme)

    restored = _only_node(flow.agent_node_list.all())
    assert restored.created_by_id == admin_acme.id
    assert restored.created_at == RECORDED_AT


@pytest.mark.django_db
def test_restore_takes_author_from_node_authorship_not_from_node_data(
    service, flow, admin_acme, member_only, member_agent_node
):
    version = service.save_version(flow, name="v1")
    for node_data in version.snapshot["nodes"]:
        node_data["created_by"] = UNKNOWN_USER_ID
    version.save(update_fields=["snapshot"])

    _restore(service, version, admin_acme)

    restored = _only_node(flow.agent_node_list.all())
    assert restored.created_by_id == member_only.id
    assert restored.created_at == RECORDED_AT


@pytest.mark.django_db
def test_restore_gives_restoring_user_a_node_recorded_without_author(
    service, flow, admin_acme, unauthored_note
):
    version = service.save_version(flow, name="v1")

    _restore(service, version, admin_acme)

    restored = _only_node(flow.graph_note_list.all())
    assert restored.created_by_id == admin_acme.id
    assert restored.created_at == RECORDED_AT


@pytest.mark.django_db
def test_restore_applies_recorded_authorship_across_node_types(
    service, flow, admin_acme, member_only, member_agent_node, unauthored_note
):
    _age(StartNode.objects.create(graph=flow, variables={}, created_by=member_only))
    version = service.save_version(flow, name="v1")

    _restore(service, version, admin_acme)

    assert _only_node(flow.agent_node_list.all()).created_by_id == member_only.id
    assert _only_node(flow.start_node_list.all()).created_by_id == member_only.id
    assert _only_node(flow.graph_note_list.all()).created_by_id == admin_acme.id
    for relation_name in ("agent_node_list", "start_node_list", "graph_note_list"):
        assert _only_node(getattr(flow, relation_name).all()).created_at == RECORDED_AT


@pytest.mark.django_db
def test_restore_of_snapshot_without_node_authorship_authors_nodes_with_restoring_user(
    service, flow, admin_acme, member_agent_node
):
    version = service.save_version(flow, name="v1")
    del version.snapshot["node_authorship"]
    version.save(update_fields=["snapshot"])
    restore_started_at = timezone.now()

    _restore(service, version, admin_acme)

    restored = _only_node(flow.agent_node_list.all())
    assert restored.created_by_id == admin_acme.id
    assert restored.created_at >= restore_started_at


@pytest.mark.django_db
def test_restore_backup_records_node_authorship_of_the_replaced_content(
    service, flow, admin_acme, member_only, member_agent_node
):
    version = service.save_version(flow, name="v1")
    flow.refresh_from_db()

    result = service.restore_version(
        version, expected_save_version=flow.save_version, backup=True, user=admin_acme
    )

    backup = flow.versions.get(pk=result["auto_backup_version_id"])
    assert backup.snapshot["node_authorship"] == {
        str(member_agent_node.id): {
            "created_by": member_only.id,
            "created_at": RECORDED_AT.isoformat(),
        }
    }


# ---- create_graph_from_version ----


@pytest.mark.django_db
def test_create_graph_from_version_authors_nodes_with_acting_user_and_fresh_created_at(
    service, flow, admin_acme, member_agent_node
):
    version = service.save_version(flow, name="v1")
    creation_started_at = timezone.now()

    result = service.create_graph_from_version(version, user=admin_acme)

    new_node = _only_node(AgentNode.objects.filter(graph_id=result["graph_id"]))
    assert new_node.created_by_id == admin_acme.id
    assert new_node.created_at >= creation_started_at


# ---- dropped nodes, query count, snapshot conversion ----


@pytest.mark.django_db
def test_restore_skips_recorded_authorship_of_a_node_dropped_by_filtering(
    service, flow, admin_acme, member_only, member_agent_node
):
    version = service.save_version(flow, name="v1")
    dropped_node_id = member_agent_node.id + 1_000_000
    version.snapshot["nodes"].append(
        {"id": dropped_node_id, "node_type": "CrewNode", "node_name": "retired"}
    )
    version.snapshot["node_authorship"][str(dropped_node_id)] = {
        "created_by": member_only.id,
        "created_at": RECORDED_AT.isoformat(),
    }
    version.save(update_fields=["snapshot"])

    result = _restore(service, version, admin_acme)

    assert [warning["type"] for warning in result["warnings"]] == ["node_type_unsupported"]
    restored = _only_node(flow.agent_node_list.all())
    assert restored.created_by_id == member_only.id
    assert restored.created_at == RECORDED_AT


def _count_restore_queries(manager, graph, user) -> int:
    recorded_authorship = manager.collect_node_authorship(graph=graph)
    node_mapper = IDMapper()
    for node_id in recorded_authorship:
        node_mapper.map(NODE_MAPPING_KEY, int(node_id), int(node_id))
    with CaptureQueriesContext(connection) as context:
        manager.restore_node_authorship(
            graph=graph,
            recorded_authorship=recorded_authorship,
            node_mapper=node_mapper,
            user=user,
        )
    return len(context.captured_queries)


@pytest.mark.django_db
def test_restore_node_authorship_query_count_does_not_grow_with_node_count(
    manager, acme, admin_acme, member_only
):
    small_flow = Graph.objects.create(name="small", org=acme)
    large_flow = Graph.objects.create(name="large", org=acme)
    AgentNode.objects.create(graph=small_flow, node_name="agent", created_by=member_only)
    for index in range(4):
        AgentNode.objects.create(graph=large_flow, node_name=f"agent {index}", created_by=member_only)

    assert _count_restore_queries(manager, small_flow, admin_acme) == _count_restore_queries(
        manager, large_flow, admin_acme
    )


@pytest.mark.django_db
def test_snapshot_conversion_keeps_node_authorship(manager):
    node_authorship = {"1": {"created_by": 7, "created_at": RECORDED_AT.isoformat()}}

    converted = manager.convert_snapshot_to_current_version(
        {"version": 1, "nodes": [], "node_authorship": node_authorship}
    )

    assert converted["node_authorship"] == node_authorship
