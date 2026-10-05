"""Graph versioning keeps each node's last edit across a restore."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from rbac.authorship import record_last_edit
from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models import OrganizationUser, ResourceLastEdit
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


def _last_edit_of(instance) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    ).first()


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="last-edited-flow", org=acme)


@pytest.fixture
def member_edited_agent_node(flow, member_only):
    node = AgentNode.objects.create(graph=flow, node_name="agent")
    record_last_edit(node, member_only, edited_at=RECORDED_AT)
    return node


@pytest.fixture
def never_edited_note(flow):
    return GraphNote.objects.create(graph=flow, content="note")


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
def test_save_version_records_last_edit_of_every_edited_node(
    service, flow, member_only, member_edited_agent_node, never_edited_note
):
    system_edited_note = GraphNote.objects.create(graph=flow, content="system")
    record_last_edit(system_edited_note, SystemServicePrincipal(), edited_at=RECORDED_AT)

    version = service.save_version(flow, name="v1")

    assert version.snapshot["node_last_edit"] == {
        str(member_edited_agent_node.id): {
            "edited_by": member_only.id,
            "edited_at": RECORDED_AT.isoformat(),
        },
        str(system_edited_note.id): {"edited_by": None, "edited_at": RECORDED_AT.isoformat()},
    }


@pytest.mark.django_db
def test_save_version_leaves_node_last_edit_out_of_the_node_data(
    service, flow, member_edited_agent_node
):
    version = service.save_version(flow, name="v1")

    node_data = json.dumps(version.snapshot["nodes"], default=str)
    assert "last_edited" not in node_data
    assert "edited_by" not in node_data


@pytest.mark.django_db
def test_graph_export_carries_no_node_last_edit(service, flow, member_edited_agent_node):
    service.save_version(flow, name="v1")

    export_data = ExportService(entity_registry).export_entities(EntityType.GRAPH, [flow.id])

    exported = json.dumps(export_data, default=str)
    assert "node_last_edit" not in exported
    assert "last_edited" not in exported


# ---- restore_version ----


@pytest.mark.django_db
def test_restore_gives_recreated_nodes_the_recorded_last_edit(
    service, flow, acme, role_org_admin, admin_acme, member_only, member_edited_agent_node
):
    version = service.save_version(flow, name="v1")
    later_editor = type(admin_acme).objects.create_user(
        email="later-editor@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=later_editor, org=acme, role=role_org_admin)
    record_last_edit(member_edited_agent_node, later_editor)

    _restore(service, version, admin_acme)

    restored = _only_node(flow.agent_node_list.all())
    assert restored.id != member_edited_agent_node.id
    last_edit = _last_edit_of(restored)
    assert last_edit.edited_by_id == member_only.id
    assert last_edit.edited_at == RECORDED_AT


@pytest.mark.django_db
def test_restore_keeps_a_recorded_system_edit_without_editor(service, flow, admin_acme):
    note = GraphNote.objects.create(graph=flow, content="note")
    record_last_edit(note, SystemServicePrincipal(), edited_at=RECORDED_AT)
    version = service.save_version(flow, name="v1")

    _restore(service, version, admin_acme)

    last_edit = _last_edit_of(_only_node(flow.graph_note_list.all()))
    assert last_edit.edited_by_id is None
    assert last_edit.edited_at == RECORDED_AT


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
def test_restore_drops_the_editor_who_is_no_longer_a_member_but_keeps_the_time(
    service, flow, admin_acme, member_edited_agent_node, membership_losses, membership_loss
):
    version = service.save_version(flow, name="v1")
    membership_losses[membership_loss]()

    _restore(service, version, admin_acme)

    last_edit = _last_edit_of(_only_node(flow.agent_node_list.all()))
    assert last_edit.edited_by_id is None
    assert last_edit.edited_at == RECORDED_AT


@pytest.mark.django_db
def test_restore_drops_an_unknown_recorded_editor_but_keeps_the_time(
    service, flow, admin_acme, member_edited_agent_node
):
    version = service.save_version(flow, name="v1")
    for entry in version.snapshot["node_last_edit"].values():
        entry["edited_by"] = UNKNOWN_USER_ID
    version.save(update_fields=["snapshot"])

    _restore(service, version, admin_acme)

    last_edit = _last_edit_of(_only_node(flow.agent_node_list.all()))
    assert last_edit.edited_by_id is None
    assert last_edit.edited_at == RECORDED_AT


@pytest.mark.django_db
def test_restore_records_restoring_user_on_a_node_without_recorded_last_edit(
    service, flow, admin_acme, never_edited_note
):
    version = service.save_version(flow, name="v1")
    restore_started_at = timezone.now()

    _restore(service, version, admin_acme)

    last_edit = _last_edit_of(_only_node(flow.graph_note_list.all()))
    assert last_edit.edited_by_id == admin_acme.id
    assert last_edit.edited_at >= restore_started_at


@pytest.mark.django_db
def test_restore_of_snapshot_without_node_last_edit_records_restoring_user(
    service, flow, admin_acme, member_edited_agent_node
):
    version = service.save_version(flow, name="v1")
    del version.snapshot["node_last_edit"]
    version.save(update_fields=["snapshot"])
    restore_started_at = timezone.now()

    _restore(service, version, admin_acme)

    last_edit = _last_edit_of(_only_node(flow.agent_node_list.all()))
    assert last_edit.edited_by_id == admin_acme.id
    assert last_edit.edited_at >= restore_started_at


@pytest.mark.django_db
def test_restore_applies_recorded_last_edits_across_node_types(
    service, flow, admin_acme, member_only, member_edited_agent_node, never_edited_note
):
    start_node = StartNode.objects.create(graph=flow, variables={})
    record_last_edit(start_node, member_only, edited_at=RECORDED_AT)
    version = service.save_version(flow, name="v1")

    _restore(service, version, admin_acme)

    assert _last_edit_of(_only_node(flow.agent_node_list.all())).edited_by_id == member_only.id
    assert _last_edit_of(_only_node(flow.start_node_list.all())).edited_by_id == member_only.id
    assert _last_edit_of(_only_node(flow.graph_note_list.all())).edited_by_id == admin_acme.id


@pytest.mark.django_db
def test_restore_records_the_graph_as_edited_by_restoring_user(
    service, flow, admin_acme, member_only, member_edited_agent_node
):
    record_last_edit(flow, member_only, edited_at=RECORDED_AT)
    version = service.save_version(flow, name="v1")
    restore_started_at = timezone.now()

    _restore(service, version, admin_acme)

    last_edit = _last_edit_of(flow)
    assert last_edit.edited_by_id == admin_acme.id
    assert last_edit.edited_at >= restore_started_at


@pytest.mark.django_db
def test_restore_without_acting_user_keeps_recorded_node_last_edits_and_graph_last_edit(
    service, flow, member_only, member_edited_agent_node, never_edited_note
):
    record_last_edit(flow, member_only, edited_at=RECORDED_AT)
    version = service.save_version(flow, name="v1")

    _restore(service, version, None)

    assert _last_edit_of(_only_node(flow.agent_node_list.all())).edited_by_id == member_only.id
    assert _last_edit_of(_only_node(flow.graph_note_list.all())) is None
    graph_last_edit = _last_edit_of(flow)
    assert graph_last_edit.edited_by_id == member_only.id
    assert graph_last_edit.edited_at == RECORDED_AT


@pytest.mark.django_db
def test_restore_backup_records_node_last_edit_of_the_replaced_content(
    service, flow, admin_acme, member_only, member_edited_agent_node
):
    version = service.save_version(flow, name="v1")
    flow.refresh_from_db()

    result = service.restore_version(
        version, expected_save_version=flow.save_version, backup=True, user=admin_acme
    )

    backup = flow.versions.get(pk=result["auto_backup_version_id"])
    assert backup.snapshot["node_last_edit"] == {
        str(member_edited_agent_node.id): {
            "edited_by": member_only.id,
            "edited_at": RECORDED_AT.isoformat(),
        }
    }


@pytest.mark.django_db
def test_restore_skips_recorded_last_edit_of_a_node_dropped_by_filtering(
    service, flow, admin_acme, member_only, member_edited_agent_node
):
    version = service.save_version(flow, name="v1")
    dropped_node_id = member_edited_agent_node.id + 1_000_000
    version.snapshot["nodes"].append(
        {"id": dropped_node_id, "node_type": "CrewNode", "node_name": "retired"}
    )
    version.snapshot["node_last_edit"][str(dropped_node_id)] = {
        "edited_by": member_only.id,
        "edited_at": RECORDED_AT.isoformat(),
    }
    version.save(update_fields=["snapshot"])

    result = _restore(service, version, admin_acme)

    assert [warning["type"] for warning in result["warnings"]] == ["node_type_unsupported"]
    last_edit = _last_edit_of(_only_node(flow.agent_node_list.all()))
    assert last_edit.edited_by_id == member_only.id
    assert last_edit.edited_at == RECORDED_AT


# ---- create_graph_from_version ----


@pytest.mark.django_db
def test_create_graph_from_version_records_acting_user_on_graph_and_nodes(
    service, flow, admin_acme, member_only, member_edited_agent_node, never_edited_note
):
    record_last_edit(flow, member_only, edited_at=RECORDED_AT)
    version = service.save_version(flow, name="v1")
    creation_started_at = timezone.now()

    result = service.create_graph_from_version(version, user=admin_acme)

    new_graph = Graph.objects.get(pk=result["graph_id"])
    new_nodes = [
        _only_node(AgentNode.objects.filter(graph=new_graph)),
        _only_node(GraphNote.objects.filter(graph=new_graph)),
    ]
    for resource in (new_graph, *new_nodes):
        last_edit = _last_edit_of(resource)
        assert last_edit.edited_by_id == admin_acme.id
        assert last_edit.edited_at >= creation_started_at
    assert _last_edit_of(flow).edited_by_id == member_only.id


@pytest.mark.django_db
def test_create_graph_from_version_without_acting_user_records_nothing(
    service, flow, member_edited_agent_node
):
    version = service.save_version(flow, name="v1")

    result = service.create_graph_from_version(version, user=None)

    new_graph = Graph.objects.get(pk=result["graph_id"])
    assert _last_edit_of(new_graph) is None
    assert _last_edit_of(_only_node(AgentNode.objects.filter(graph=new_graph))) is None


# ---- query count, snapshot conversion ----


def _count_restore_queries(manager, graph) -> int:
    recorded_last_edits = manager.collect_node_last_edits(graph=graph)
    node_mapper = IDMapper()
    for node_id in recorded_last_edits:
        node_mapper.map(NODE_MAPPING_KEY, int(node_id), int(node_id))
    with CaptureQueriesContext(connection) as context:
        manager.restore_node_last_edits(
            graph=graph,
            recorded_last_edits=recorded_last_edits,
            node_mapper=node_mapper,
        )
    return len(context.captured_queries)


@pytest.mark.django_db
def test_restore_node_last_edits_query_count_does_not_grow_with_node_count(
    manager, acme, member_only
):
    small_flow = Graph.objects.create(name="small", org=acme)
    large_flow = Graph.objects.create(name="large", org=acme)
    record_last_edit(AgentNode.objects.create(graph=small_flow, node_name="agent"), member_only)
    for index in range(4):
        node = AgentNode.objects.create(graph=large_flow, node_name=f"agent {index}")
        record_last_edit(node, member_only)

    assert _count_restore_queries(manager, small_flow) == _count_restore_queries(
        manager, large_flow
    )


@pytest.mark.django_db
def test_collect_node_last_edits_query_count_does_not_grow_with_node_count(
    manager, acme, member_only
):
    small_flow = Graph.objects.create(name="small", org=acme)
    large_flow = Graph.objects.create(name="large", org=acme)
    record_last_edit(AgentNode.objects.create(graph=small_flow, node_name="agent"), member_only)
    for index in range(4):
        node = AgentNode.objects.create(graph=large_flow, node_name=f"agent {index}")
        record_last_edit(node, member_only, edited_at=timezone.now() - timedelta(hours=index))

    with CaptureQueriesContext(connection) as small_context:
        manager.collect_node_last_edits(graph=small_flow)
    with CaptureQueriesContext(connection) as large_context:
        collected = manager.collect_node_last_edits(graph=large_flow)

    assert len(collected) == 4
    assert len(small_context.captured_queries) == len(large_context.captured_queries)


@pytest.mark.django_db
def test_snapshot_conversion_keeps_node_last_edit(manager):
    node_last_edit = {"1": {"edited_by": 7, "edited_at": RECORDED_AT.isoformat()}}

    converted = manager.convert_snapshot_to_current_version(
        {"version": 1, "nodes": [], "node_last_edit": node_last_edit}
    )

    assert converted["node_last_edit"] == node_last_edit
