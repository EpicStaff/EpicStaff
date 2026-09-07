"""Layer 2 tests: GraphVersioningManager."""

import pytest

from tables.graph_versioning.constants import _GRAPH_RELATION_NAMES
from tables.graph_versioning.manager import GraphVersioningManager
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.constants import NODE_MAPPING_KEY
from tables.models import Graph, Edge, AgentNode, StartNode, GraphOrganization
from tests.fixtures import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Group A: filter_snapshot — pure dict logic, no DB
# ---------------------------------------------------------------------------


def test_filter_snapshot_nulls_fk_for_agent_node_when_definition_missing(
    manager, agent_node_dict
):
    snapshot = {
        "nodes": [agent_node_dict],
        "edge_list": [],
        "conditional_edge_list": [],
    }
    missing = {EntityType.AGENT_DEFINITION.value: [agent_node_dict["agent_definition"]]}

    filtered, warnings = manager.filter_snapshot(snapshot, missing)

    assert len(filtered["nodes"]) == 1
    assert filtered["nodes"][0]["agent_definition"] is None
    assert [w["type"] for w in warnings] == ["fk_nulled"]


def test_filter_snapshot_keeps_agent_node_untouched_when_definition_available(
    manager, agent_node_dict
):
    snapshot = {
        "nodes": [agent_node_dict],
        "edge_list": [],
        "conditional_edge_list": [],
    }
    missing = {}

    filtered, warnings = manager.filter_snapshot(snapshot, missing)

    assert len(filtered["nodes"]) == 1
    assert filtered["nodes"][0]["id"] == agent_node_dict["id"]
    assert (
        filtered["nodes"][0]["agent_definition"] == agent_node_dict["agent_definition"]
    )
    assert warnings == []


def test_filter_edges_drops_edge_to_skipped_node(manager, start_node_dict):
    SKIPPED_NODE_ID = 777
    edges = [{"start_node_id": start_node_dict["id"], "end_node_id": SKIPPED_NODE_ID}]

    kept, warnings = manager._filter_edges(edges, {SKIPPED_NODE_ID})

    assert kept == []
    assert [w["type"] for w in warnings] == ["edge_dropped"]


def test_filter_edges_drops_edge_from_skipped_node(manager, start_node_dict):
    SKIPPED_NODE_ID = 777
    edges = [{"start_node_id": SKIPPED_NODE_ID, "end_node_id": start_node_dict["id"]}]

    kept, warnings = manager._filter_edges(edges, {SKIPPED_NODE_ID})

    assert kept == []
    assert [w["type"] for w in warnings] == ["edge_dropped"]


def test_filter_edges_keeps_edge_between_kept_nodes(manager, start_node_dict):
    edges = [{"start_node_id": start_node_dict["id"], "end_node_id": 1234}]

    kept, warnings = manager._filter_edges(edges, set())

    assert kept == edges
    assert warnings == []


def test_filter_conditional_edges_drops_edge_from_skipped_node(manager):
    SKIPPED_NODE_ID = 777
    conditional_edges = [{"source_node_id": SKIPPED_NODE_ID, "condition": "x > 0"}]

    kept, warnings = manager._filter_conditional_edges(
        conditional_edges, {SKIPPED_NODE_ID}
    )

    assert kept == []
    assert len(warnings) == 1
    assert warnings[0]["type"] == "edge_dropped"
    assert "Conditional edge" in warnings[0]["reason"]


def test_filter_snapshot_does_not_mutate_input(manager, agent_node_dict):
    original_definition_id = agent_node_dict["agent_definition"]
    snapshot = {
        "nodes": [agent_node_dict],
        "edge_list": [],
        "conditional_edge_list": [],
    }
    missing = {EntityType.AGENT_DEFINITION.value: [agent_node_dict["agent_definition"]]}

    manager.filter_snapshot(snapshot, missing)

    assert agent_node_dict["agent_definition"] == original_definition_id


SKIPPED_NODE_ID = 777


def test_clean_decision_table_refs_clears_default_next_node_id(
    manager, make_decision_table_node
):
    decision_node = make_decision_table_node(default_next=SKIPPED_NODE_ID)

    warnings = manager._clean_decision_table_refs([decision_node], {SKIPPED_NODE_ID})

    assert decision_node["default_next_node_id"] is None
    assert [w["type"] for w in warnings] == ["decision_table_ref_cleared"]


def test_clean_decision_table_refs_clears_next_error_node_id(
    manager, make_decision_table_node
):
    decision_node = make_decision_table_node(next_error=SKIPPED_NODE_ID)

    warnings = manager._clean_decision_table_refs([decision_node], {SKIPPED_NODE_ID})

    assert decision_node["next_error_node_id"] is None
    assert [w["type"] for w in warnings] == ["decision_table_ref_cleared"]


def test_clean_decision_table_refs_clears_condition_group_next_node_id(
    manager, make_decision_table_node
):
    decision_node = make_decision_table_node(
        condition_groups=[{"group_name": "g1", "next_node_id": SKIPPED_NODE_ID}]
    )

    warnings = manager._clean_decision_table_refs([decision_node], {SKIPPED_NODE_ID})

    assert decision_node["condition_groups"][0]["next_node_id"] is None
    assert len(warnings) == 1
    assert "condition_groups[g1]" in warnings[0]["field"]


def test_clean_decision_table_refs_keeps_live_references(
    manager, make_decision_table_node
):
    decision_node = make_decision_table_node(default_next=SKIPPED_NODE_ID)

    warnings = manager._clean_decision_table_refs([decision_node], set())

    assert decision_node["default_next_node_id"] == SKIPPED_NODE_ID
    assert warnings == []


# ---------------------------------------------------------------------------
# Group B: change_old_warnings_ids — pure logic, no DB
# ---------------------------------------------------------------------------


def test_change_old_warnings_ids_remaps_node_id(manager):
    OLD_ID, NEW_ID = 10, 999
    mapper = IDMapper()
    mapper.map(NODE_MAPPING_KEY, OLD_ID, NEW_ID, was_created=True)
    warnings = [{"type": "fk_nulled", "node_id": OLD_ID, "field": "llm_config"}]

    manager.change_old_warnings_ids(warnings, mapper)

    assert warnings[0]["node_id"] == NEW_ID


def test_change_old_warnings_ids_skips_warning_without_node_id(manager):
    mapper = IDMapper()
    warnings = [{"type": "node_skipped", "reason": "Missing dependency"}]

    # Should not raise
    manager.change_old_warnings_ids(warnings, mapper)

    assert "node_id" not in warnings[0]


def test_change_old_warnings_ids_handles_multiple_warnings(manager):
    OLD_ID_A, NEW_ID_A = 10, 100
    OLD_ID_B, NEW_ID_B = 20, 200
    mapper = IDMapper()
    mapper.map(NODE_MAPPING_KEY, OLD_ID_A, NEW_ID_A, was_created=True)
    mapper.map(NODE_MAPPING_KEY, OLD_ID_B, NEW_ID_B, was_created=True)

    warnings = [
        {"type": "fk_nulled", "node_id": OLD_ID_A, "field": "llm_config"},
        {"type": "node_skipped", "reason": "Missing dependency"},
        {"type": "fk_nulled", "node_id": OLD_ID_B, "field": "subgraph"},
    ]

    manager.change_old_warnings_ids(warnings, mapper)

    assert warnings[0]["node_id"] == NEW_ID_A
    assert "node_id" not in warnings[1]
    assert warnings[2]["node_id"] == NEW_ID_B


# ---------------------------------------------------------------------------
# Group C: validate_dependencies — DB tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_validate_dependencies_all_available(manager, agent_definition, llm_config):
    dependencies = {
        EntityType.AGENT_DEFINITION.value: [agent_definition.id],
        EntityType.LLM_CONFIG.value: [llm_config.id],
    }

    result = manager.validate_dependencies(dependencies)

    assert agent_definition.id in result["available"][EntityType.AGENT_DEFINITION.value]
    assert llm_config.id in result["available"][EntityType.LLM_CONFIG.value]
    assert result["missing"][EntityType.AGENT_DEFINITION.value] == []
    assert result["missing"][EntityType.LLM_CONFIG.value] == []


@pytest.mark.django_db
def test_validate_dependencies_all_missing(manager):
    dependencies = {EntityType.AGENT_DEFINITION.value: [99998, 99999]}

    result = manager.validate_dependencies(dependencies)

    assert result["available"][EntityType.AGENT_DEFINITION.value] == []
    assert set(result["missing"][EntityType.AGENT_DEFINITION.value]) == {
        99998,
        99999,
    }


@pytest.mark.django_db
def test_validate_dependencies_mixed_available_and_missing(manager, agent_definition):
    dependencies = {EntityType.AGENT_DEFINITION.value: [agent_definition.id, 99999]}

    result = manager.validate_dependencies(dependencies)

    assert agent_definition.id in result["available"][EntityType.AGENT_DEFINITION.value]
    assert 99999 in result["missing"][EntityType.AGENT_DEFINITION.value]


@pytest.mark.django_db
def test_validate_dependencies_filters_none_ids(manager, agent_definition):
    dependencies = {
        EntityType.AGENT_DEFINITION.value: [agent_definition.id, None, None]
    }

    result = manager.validate_dependencies(dependencies)

    assert agent_definition.id in result["available"][EntityType.AGENT_DEFINITION.value]
    assert result["missing"][EntityType.AGENT_DEFINITION.value] == []


@pytest.mark.django_db
def test_validate_dependencies_empty_input(manager):
    result = manager.validate_dependencies({})

    assert result == {"available": {}, "missing": {}}


# ---------------------------------------------------------------------------
# Group D: snapshot & dependency collection — DB tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_snapshot_returns_dict_with_nodes_key(manager, graph):
    result = manager.create_snapshot(graph)

    assert isinstance(result, dict)
    assert "nodes" in result


@pytest.mark.django_db
def test_collect_dependencies_empty_graph(manager, graph):
    result = manager.collect_dependencies(graph)

    # Either no keys or all listed IDs are empty
    for _entity_type, ids in result.items():
        assert ids == []


@pytest.mark.django_db
def test_collect_dependencies_with_agent_node(manager, graph, agent_definition):
    AgentNode.objects.create(
        graph=graph, node_name="an", agent_definition=agent_definition
    )

    result = manager.collect_dependencies(graph)

    assert EntityType.AGENT_DEFINITION.value in result
    assert agent_definition.id in result[EntityType.AGENT_DEFINITION.value]


# ---------------------------------------------------------------------------
# Group E: wipe & update graph — DB tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_wipe_graph_children_removes_agent_nodes(manager, graph, agent_definition):
    AgentNode.objects.create(
        graph=graph, node_name="wipe_test", agent_definition=agent_definition
    )
    assert graph.agent_node_list.count() == 1

    manager._wipe_graph_children(graph)

    assert graph.agent_node_list.count() == 0


@pytest.mark.django_db
def test_wipe_graph_children_deletes_orphan_python_codes(manager, graph):
    from tables.models import PythonCode, PythonNode

    code = PythonCode.objects.create(
        code="def main(): return 1",
        entrypoint="main",
        libraries="",
        global_kwargs={},
    )
    PythonNode.objects.create(graph=graph, python_code=code)

    manager._wipe_graph_children(graph)

    assert not PythonCode.objects.filter(id=code.id).exists()


@pytest.mark.django_db
def test_wipe_graph_children_keeps_shared_python_codes(
    manager, graph, python_code, python_code_tool
):
    from tables.models import PythonNode

    # python_code_tool already references python_code (shared)
    node = PythonNode.objects.create(graph=graph, python_code=python_code)

    manager._wipe_graph_children(graph)

    # PythonNode must be gone
    assert not PythonNode.objects.filter(id=node.id).exists()
    # PythonCode must survive because python_code_tool still references it
    from tables.models import PythonCode

    assert PythonCode.objects.filter(id=python_code.id).exists()


@pytest.mark.django_db
def test_update_graph_scalars_updates_name(manager, graph):
    snapshot = {"name": "restored name"}

    manager._update_graph_scalars(graph, snapshot)
    graph.refresh_from_db()

    assert graph.name == "restored name"


@pytest.mark.django_db
def test_update_graph_scalars_ignores_excluded_fields(manager, graph):
    original_id = graph.id
    original_created_at = graph.created_at
    snapshot = {"id": 9999, "created_at": "2000-01-01T00:00:00Z", "name": "safe name"}

    manager._update_graph_scalars(graph, snapshot)
    graph.refresh_from_db()

    assert graph.id == original_id
    assert graph.created_at == original_created_at


# ---------------------------------------------------------------------------
# Group F: apply_snapshot_to_graph & _build_identity_id_mapper — DB & no-DB
# ---------------------------------------------------------------------------


def test_build_identity_id_mapper_creates_identity_mappings(manager):
    available_deps = {
        EntityType.AGENT_DEFINITION.value: [10, 20],
        EntityType.LLM_CONFIG.value: [5],
    }

    id_mapper = manager._build_identity_id_mapper(available_deps)

    # Identity: old_id == new_id
    assert id_mapper.get(EntityType.AGENT_DEFINITION, 10) == 10
    assert id_mapper.get(EntityType.AGENT_DEFINITION, 20) == 20
    assert id_mapper.get(EntityType.LLM_CONFIG, 5) == 5
    # was_created=False because deps already existed in DB
    assert id_mapper.was_created(EntityType.AGENT_DEFINITION, 10) is False


def test_build_identity_id_mapper_skips_unknown_entity_types(manager):
    available_deps = {
        "UnknownEntityType": [1, 2, 3],
    }

    id_mapper = manager._build_identity_id_mapper(available_deps)

    # No mapping should be created for unknown types
    assert not id_mapper.has_mapping("UnknownEntityType", 1)


@pytest.mark.django_db
def test_apply_snapshot_to_graph_round_trip(manager, graph, agent_definition):
    AgentNode.objects.create(
        graph=graph, node_name="original_an", agent_definition=agent_definition
    )
    snapshot = manager.create_snapshot(graph)
    available_deps = {EntityType.AGENT_DEFINITION.value: [agent_definition.id]}

    result = manager.apply_snapshot_to_graph(graph, snapshot, available_deps)

    # Method returns an IDMapper instance
    assert isinstance(result, IDMapper)
    # Graph still has exactly one AgentNode after wipe + recreate
    assert graph.agent_node_list.count() == 1
    # Recreated node references the same agent definition
    recreated = graph.agent_node_list.first()
    assert recreated.agent_definition_id == agent_definition.id


# ---------------------------------------------------------------------------
# Group G: create_graph_from_snapshot — DB tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_graph_from_snapshot_returns_graph_and_idmapper(
    manager, graph, default_org
):
    snapshot = manager.create_snapshot(graph)

    result = manager.create_graph_from_snapshot(
        snapshot, available_deps={}, version_name="v1"
    )

    assert isinstance(result, tuple)
    assert len(result) == 2
    new_graph, node_mapper = result
    assert isinstance(new_graph, Graph)
    assert isinstance(node_mapper, IDMapper)


@pytest.mark.django_db
def test_create_graph_from_snapshot_creates_new_graph_row(manager, graph, default_org):
    snapshot = manager.create_snapshot(graph)

    new_graph, _ = manager.create_graph_from_snapshot(
        snapshot, available_deps={}, version_name="v1"
    )

    assert Graph.objects.filter(id=new_graph.id).exists()
    assert new_graph.id != graph.id


@pytest.mark.django_db
def test_create_graph_from_snapshot_uses_version_name_as_graph_name(
    manager, graph, default_org
):
    snapshot = manager.create_snapshot(graph)

    new_graph, _ = manager.create_graph_from_snapshot(
        snapshot, available_deps={}, version_name="My Version"
    )

    assert new_graph.name == "My Version"


@pytest.mark.django_db
def test_create_graph_from_snapshot_deduplicates_name_when_taken(
    manager, graph, default_org
):
    Graph.objects.create(name="My Version")
    snapshot = manager.create_snapshot(graph)

    new_graph, _ = manager.create_graph_from_snapshot(
        snapshot, available_deps={}, version_name="My Version"
    )

    assert new_graph.name == "My Version (2)"


@pytest.mark.django_db
def test_create_graph_from_snapshot_does_not_mutate_input_snapshot(
    manager, graph, default_org
):
    snapshot = manager.create_snapshot(graph)
    original_id = snapshot.get("id")
    original_nodes_len = len(snapshot.get("nodes", []))

    manager.create_graph_from_snapshot(snapshot, available_deps={}, version_name="v1")

    assert snapshot.get("id") == original_id
    assert len(snapshot.get("nodes", [])) == original_nodes_len


@pytest.mark.django_db
def test_create_graph_from_snapshot_links_to_default_organization(
    manager, graph, default_org
):
    snapshot = manager.create_snapshot(graph)

    new_graph, _ = manager.create_graph_from_snapshot(
        snapshot, available_deps={}, version_name="v1"
    )

    assert GraphOrganization.objects.filter(graph=new_graph).exists()
    assert new_graph.org == default_org


@pytest.mark.django_db
def test_create_graph_from_snapshot_recreates_agent_node(
    manager, graph, agent_definition, default_org
):
    AgentNode.objects.create(
        graph=graph, node_name="an", agent_definition=agent_definition
    )
    snapshot = manager.create_snapshot(graph)
    available_deps = {EntityType.AGENT_DEFINITION.value: [agent_definition.id]}

    new_graph, _ = manager.create_graph_from_snapshot(
        snapshot, available_deps=available_deps, version_name="v1"
    )

    assert new_graph.agent_node_list.count() == 1
    assert new_graph.agent_node_list.first().agent_definition_id == agent_definition.id


@pytest.mark.django_db
def test_create_graph_from_snapshot_node_mapper_maps_old_to_new_node_id(
    manager, graph, agent_definition, default_org
):
    AgentNode.objects.create(
        graph=graph, node_name="an", agent_definition=agent_definition
    )
    snapshot = manager.create_snapshot(graph)
    available_deps = {EntityType.AGENT_DEFINITION.value: [agent_definition.id]}

    agent_node_entry = next(
        n for n in snapshot["nodes"] if n["node_type"] == NodeType.AGENT_NODE
    )
    old_node_id = agent_node_entry["id"]

    new_graph, node_mapper = manager.create_graph_from_snapshot(
        snapshot, available_deps=available_deps, version_name="v1"
    )

    new_agent_node = new_graph.agent_node_list.first()
    assert node_mapper.get(NODE_MAPPING_KEY, old_node_id) == new_agent_node.id


@pytest.mark.django_db
def test_create_graph_from_snapshot_recreates_edge_with_remapped_node_ids(
    manager, graph, agent_definition, default_org
):
    start_node = StartNode.objects.create(graph=graph, variables={})
    agent_node = AgentNode.objects.create(
        graph=graph, node_name="an", agent_definition=agent_definition
    )
    Edge.objects.create(
        graph=graph,
        start_node_id=start_node.id,
        end_node_id=agent_node.id,
    )
    snapshot = manager.create_snapshot(graph)
    available_deps = {EntityType.AGENT_DEFINITION.value: [agent_definition.id]}

    new_graph, _ = manager.create_graph_from_snapshot(
        snapshot, available_deps=available_deps, version_name="v1"
    )

    assert new_graph.edge_list.count() == 1
    new_edge = new_graph.edge_list.first()
    original_node_ids = {start_node.id, agent_node.id}
    assert new_edge.start_node_id not in original_node_ids
    assert new_edge.end_node_id not in original_node_ids


# ---------------------------------------------------------------------------
# Group H: regression — nodes missing from _GRAPH_RELATION_NAMES
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_does_not_raise_integrity_error_for_classification_decision_table_node(
    manager, graph
):
    """
    Restore must not raise IntegrityError for ClassificationDecisionTableNode.

    Before the fix, _wipe_graph_children() did not delete
    classification_decision_table_node_list rows. The subsequent recreate
    would violate unique_graph_node_name_for_classification_dt_node.
    """
    from tables.models import ClassificationDecisionTableNode

    ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name="classifier_node",
    )
    snapshot = manager.create_snapshot(graph)

    # apply_snapshot_to_graph is the restore path: wipe + recreate
    manager.apply_snapshot_to_graph(graph, snapshot, available_deps={})

    assert graph.classification_decision_table_node_list.count() == 1
    restored = graph.classification_decision_table_node_list.first()
    assert restored.node_name == "classifier_node"


@pytest.mark.django_db
def test_restore_does_not_reject_blank_pre_python_code(manager, graph):
    """
    Restore must not raise a validation error for a blank pre/post-processing code block.

    Before the fix, PythonCodeImportSerializer required "code" to be non-blank,
    so a ClassificationDecisionTableNode whose pre_python_code.code was ""
    (a normal, saveable state in the editor) failed to restore.
    """
    from tables.models import ClassificationDecisionTableNode, PythonCode

    pre_python_code = PythonCode.objects.create(code="")
    ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name="classifier_node",
        pre_python_code=pre_python_code,
    )
    snapshot = manager.create_snapshot(graph)

    manager.apply_snapshot_to_graph(graph, snapshot, available_deps={})

    restored = graph.classification_decision_table_node_list.first()
    assert restored.pre_python_code.code == ""


@pytest.mark.django_db
def test_restore_does_not_duplicate_schedule_trigger_node(manager, graph):
    """
    Restore must not accumulate duplicate ScheduleTriggerNode rows.

    Before the fix, _wipe_graph_children() silently skipped
    schedule_trigger_node_list, so each restore appended new rows
    without removing the old ones.
    """
    from tables.models import ScheduleTriggerNode

    ScheduleTriggerNode.objects.create(
        graph=graph,
        node_name="trigger_node",
        is_active=False,
    )
    assert graph.schedule_trigger_node_list.count() == 1

    snapshot = manager.create_snapshot(graph)

    manager.apply_snapshot_to_graph(graph, snapshot, available_deps={})

    assert graph.schedule_trigger_node_list.count() == 1


@pytest.mark.django_db
def test_restore_does_not_duplicate_agent_node(manager, graph):
    """
    Restore must not accumulate duplicate AgentNode rows.

    Before the fix, _wipe_graph_children() silently skipped
    agent_node_list, so each restore appended a new snapshot copy
    on top of the existing node instead of replacing it.
    """
    from tables.models import AgentNode

    AgentNode.objects.create(graph=graph, node_name="agent_node")
    assert graph.agent_node_list.count() == 1

    snapshot = manager.create_snapshot(graph)

    manager.apply_snapshot_to_graph(graph, snapshot, available_deps={})

    assert graph.agent_node_list.count() == 1


@pytest.mark.django_db
def test_restore_does_not_duplicate_task_node(manager, graph):
    """
    Restore must not accumulate duplicate TaskNode rows.

    Before the fix, _wipe_graph_children() silently skipped
    task_node_list, so each restore appended a new snapshot copy
    on top of the existing node instead of replacing it.
    """
    from tables.models import TaskNode

    TaskNode.objects.create(graph=graph, node_name="task_node")
    assert graph.task_node_list.count() == 1

    snapshot = manager.create_snapshot(graph)

    manager.apply_snapshot_to_graph(graph, snapshot, available_deps={})

    assert graph.task_node_list.count() == 1


@pytest.mark.django_db
def test_graph_relation_names_covers_all_node_edge_note_relations(graph):
    """
    Guard against regression: every reverse relation on Graph that
    represents a node, edge, or note list must be wiped on restore.

    Derives the expected relation names directly from Graph's reverse
    relations instead of hardcoding them, so a newly added node type
    that is forgotten in _GRAPH_RELATION_NAMES fails this test.
    """
    # crew_node_list is deliberately excluded from _GRAPH_RELATION_NAMES: the
    # CrewNode model is kept only so pre-CrewAI-removal rows still load, and it
    # is neither snapshotted nor recreated on restore.
    DEPRECATED_RELATION_NAMES = {"crew_node_list"}

    reverse_accessor_names = {
        field.get_accessor_name()
        for field in Graph._meta.get_fields()
        if field.is_relation and field.auto_created and not field.concrete
    }

    expected_relation_names = {
        name
        for name in reverse_accessor_names
        if name.endswith(("_node_list", "_edge_list", "_note_list"))
        or name == "end_node"
    }

    missing_from_wipe_list = (
        expected_relation_names - set(_GRAPH_RELATION_NAMES) - DEPRECATED_RELATION_NAMES
    )

    assert missing_from_wipe_list == set()


# ---------------------------------------------------------------------------
# Group I: regression — AgentNode/TaskNode dependencies dropped on restore
#
# validate_dependencies()/_build_identity_id_mapper() used to know only about
# LLM_CONFIG, WEBHOOK_TRIGGER and GRAPH (_DEPENDENCY_ENTITY_TYPES /
# _DEPENDENCY_MODELS). AgentNode/TaskNode also depend on AGENT_DEFINITION,
# SURFACE, PYTHON_CODE_TOOL and MCP_TOOL, so those lookups silently return
# None during restore and the relations are lost.
# ---------------------------------------------------------------------------


def _restore_graph_via_real_pipeline(manager, graph, deps):
    """Mirror GraphVersioningService.restore_version's pipeline exactly."""
    snapshot = manager.create_snapshot(graph)
    deps_validation = manager.validate_dependencies(deps)
    filtered_snapshot, warnings = manager.filter_snapshot(
        snapshot, deps_validation["missing"]
    )
    manager.apply_snapshot_to_graph(
        graph, filtered_snapshot, deps_validation["available"]
    )
    return warnings


@pytest.fixture
def surface(default_org):
    from agents.models import Surface

    return Surface.objects.create(organization=default_org, name="restore-test-surface")


@pytest.fixture
def mcp_tool(default_org):
    from tables.models import McpTool

    return McpTool.objects.create(
        org=default_org,
        name="restore-test-mcp-tool",
        transport="https://example.com/mcp",
        tool_name="do_thing",
    )


@pytest.mark.django_db
def test_restore_keeps_agent_node_agent_definition(manager, graph, agent_definition):
    from tables.models import AgentNode

    AgentNode.objects.create(
        graph=graph, node_name="agent_node", agent_definition=agent_definition
    )
    deps = manager.collect_dependencies(graph)

    _restore_graph_via_real_pipeline(manager, graph, deps)

    restored = graph.agent_node_list.first()
    assert restored is not None
    assert restored.agent_definition_id == agent_definition.id


@pytest.mark.django_db
def test_restore_keeps_agent_node_surface_list(manager, graph, surface):
    from tables.models import AgentNode

    agent_node = AgentNode.objects.create(graph=graph, node_name="agent_node")
    agent_node.surface_list.set([surface])
    deps = manager.collect_dependencies(graph)

    _restore_graph_via_real_pipeline(manager, graph, deps)

    restored = graph.agent_node_list.first()
    assert list(restored.surface_list.values_list("id", flat=True)) == [surface.id]


@pytest.mark.django_db
def test_restore_keeps_agent_node_inline_surface_python_tool(
    manager, graph, python_code_tool
):
    from agents.models import AgentInlineSurface, AgentInlineSurfacePythonTool
    from tables.models import AgentNode

    agent_node = AgentNode.objects.create(graph=graph, node_name="agent_node")
    inline_surface = AgentInlineSurface.objects.create(agent_node=agent_node)
    AgentInlineSurfacePythonTool.objects.create(
        agent_inline_surface=inline_surface,
        python_tool=python_code_tool,
        mode="allow",
    )
    deps = manager.collect_dependencies(graph)

    _restore_graph_via_real_pipeline(manager, graph, deps)

    restored = graph.agent_node_list.first()
    restored_python_tool_ids = list(
        restored.inline_surface.python_tools.values_list("python_tool_id", flat=True)
    )
    assert restored_python_tool_ids == [python_code_tool.id]


@pytest.mark.django_db
def test_restore_keeps_agent_node_inline_surface_mcp_tool(manager, graph, mcp_tool):
    from agents.models import AgentInlineSurface, AgentInlineSurfaceMcpTool
    from tables.models import AgentNode

    agent_node = AgentNode.objects.create(graph=graph, node_name="agent_node")
    inline_surface = AgentInlineSurface.objects.create(agent_node=agent_node)
    AgentInlineSurfaceMcpTool.objects.create(
        agent_inline_surface=inline_surface,
        mcp_tool=mcp_tool,
        mode="allow",
    )
    deps = manager.collect_dependencies(graph)

    _restore_graph_via_real_pipeline(manager, graph, deps)

    restored = graph.agent_node_list.first()
    restored_mcp_tool_ids = list(
        restored.inline_surface.mcp_tools.values_list("mcp_tool_id", flat=True)
    )
    assert restored_mcp_tool_ids == [mcp_tool.id]


@pytest.mark.django_db
def test_restore_keeps_task_node_agent_definition(manager, graph, agent_definition):
    from tables.models import TaskNode

    TaskNode.objects.create(
        graph=graph, node_name="task_node", agent_definition=agent_definition
    )
    deps = manager.collect_dependencies(graph)

    _restore_graph_via_real_pipeline(manager, graph, deps)

    restored = graph.task_node_list.first()
    assert restored is not None
    assert restored.agent_definition_id == agent_definition.id


@pytest.mark.django_db
def test_restore_keeps_task_node_surface_list(manager, graph, surface):
    from tables.models import TaskNode

    task_node = TaskNode.objects.create(graph=graph, node_name="task_node")
    task_node.surface_list.set([surface])
    deps = manager.collect_dependencies(graph)

    _restore_graph_via_real_pipeline(manager, graph, deps)

    restored = graph.task_node_list.first()
    assert list(restored.surface_list.values_list("id", flat=True)) == [surface.id]


@pytest.mark.django_db
def test_restore_keeps_task_node_inline_surface_python_tool(
    manager, graph, python_code_tool
):
    from agents.models import InlineSurface, InlineSurfacePythonTool
    from tables.models import TaskNode

    task_node = TaskNode.objects.create(graph=graph, node_name="task_node")
    inline_surface = InlineSurface.objects.create(task_node=task_node)
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline_surface,
        python_tool=python_code_tool,
        mode="allow",
    )
    deps = manager.collect_dependencies(graph)

    _restore_graph_via_real_pipeline(manager, graph, deps)

    restored = graph.task_node_list.first()
    restored_python_tool_ids = list(
        restored.inline_surface.python_tools.values_list("python_tool_id", flat=True)
    )
    assert restored_python_tool_ids == [python_code_tool.id]


@pytest.mark.django_db
def test_restore_nulls_agent_node_agent_definition_when_deleted(
    manager, graph, agent_definition
):
    """
    Deleted AgentDefinition (SET_NULL FK) must not crash restore and must
    not silently skip the whole AgentNode — only the FK is nulled.
    """
    from tables.models import AgentNode

    AgentNode.objects.create(
        graph=graph, node_name="agent_node", agent_definition=agent_definition
    )
    deps = manager.collect_dependencies(graph)
    agent_definition.delete()

    _restore_graph_via_real_pipeline(manager, graph, deps)

    restored = graph.agent_node_list.first()
    assert restored is not None
    assert restored.agent_definition_id is None


@pytest.mark.django_db
def test_create_graph_from_snapshot_keeps_agent_node_agent_definition(
    manager, graph, agent_definition, default_org
):
    """create_graph_from_snapshot (duplicate-into-new-flow) shares
    _build_identity_id_mapper with restore, so it must benefit from the
    same fix."""
    from tables.models import AgentNode

    AgentNode.objects.create(
        graph=graph, node_name="agent_node", agent_definition=agent_definition
    )
    snapshot = manager.create_snapshot(graph)
    deps = manager.collect_dependencies(graph)
    deps_validation = manager.validate_dependencies(deps)

    new_graph, _ = manager.create_graph_from_snapshot(
        snapshot,
        deps_validation["available"],
        graph_name=graph.name,
        version_name="v1",
        org_id=default_org.id,
    )

    new_agent_node = new_graph.agent_node_list.first()
    assert new_agent_node is not None
    assert new_agent_node.agent_definition_id == agent_definition.id


# ---------------------------------------------------------------------------
# Group J: restore warnings for deleted AgentNode/TaskNode dependencies
#
# Deleting AgentDefinition/Surface/PythonCodeTool/MCPTool referenced by an
# AgentNode or TaskNode must not silently drop them on restore — a warning
# carrying node_id/node_name must be surfaced for each dropped reference.
#
# The dependency must be deleted *after* the snapshot/deps manifest are
# captured — this mirrors the real restore scenario (an older GraphVersion
# was saved while the dependency existed, and it was deleted afterwards).
# Snapshotting after deletion is meaningless here: Django's SET_NULL/CASCADE
# already scrubs the stale FK/M2M/link rows from the live graph the moment
# the dependency is deleted, so a fresh snapshot would never contain the
# missing reference in the first place.
# ---------------------------------------------------------------------------


def _restore_from_saved_snapshot(manager, graph, snapshot, deps):
    """Restore `graph` from a snapshot captured earlier, validating `deps`
    (also captured earlier) against the current DB state."""
    deps_validation = manager.validate_dependencies(deps)
    filtered_snapshot, warnings = manager.filter_snapshot(
        snapshot, deps_validation["missing"]
    )
    manager.apply_snapshot_to_graph(
        graph, filtered_snapshot, deps_validation["available"]
    )
    return warnings


@pytest.mark.django_db
def test_restore_warns_and_nulls_agent_node_agent_definition_when_deleted(
    manager, graph, agent_definition
):
    from tables.models import AgentNode

    agent_node = AgentNode.objects.create(
        graph=graph, node_name="agent_node", agent_definition=agent_definition
    )
    snapshot = manager.create_snapshot(graph)
    deps = manager.collect_dependencies(graph)
    agent_definition.delete()

    warnings = _restore_from_saved_snapshot(manager, graph, snapshot, deps)

    restored = graph.agent_node_list.first()
    assert restored.agent_definition_id is None

    fk_nulled_warnings = [w for w in warnings if w["type"] == "fk_nulled"]
    assert len(fk_nulled_warnings) == 1
    assert fk_nulled_warnings[0]["node_name"] == "agent_node"
    assert fk_nulled_warnings[0]["node_id"] == agent_node.id


@pytest.mark.django_db
def test_restore_warns_and_nulls_task_node_agent_definition_when_deleted(
    manager, graph, agent_definition
):
    from tables.models import TaskNode

    task_node = TaskNode.objects.create(
        graph=graph, node_name="task_node", agent_definition=agent_definition
    )
    snapshot = manager.create_snapshot(graph)
    deps = manager.collect_dependencies(graph)
    agent_definition.delete()

    warnings = _restore_from_saved_snapshot(manager, graph, snapshot, deps)

    restored = graph.task_node_list.first()
    assert restored is not None
    assert restored.agent_definition_id is None

    fk_nulled_warnings = [w for w in warnings if w["type"] == "fk_nulled"]
    assert len(fk_nulled_warnings) == 1
    assert fk_nulled_warnings[0]["node_name"] == "task_node"
    assert fk_nulled_warnings[0]["node_id"] == task_node.id


@pytest.mark.django_db
def test_restore_warns_and_drops_agent_node_surface_when_deleted(
    manager, graph, surface, default_org
):
    from agents.models import Surface
    from tables.models import AgentNode

    surviving_surface = Surface.objects.create(
        organization=default_org, name="surviving-surface"
    )
    agent_node = AgentNode.objects.create(graph=graph, node_name="agent_node")
    agent_node.surface_list.set([surface, surviving_surface])
    snapshot = manager.create_snapshot(graph)
    deps = manager.collect_dependencies(graph)
    deleted_surface_id = surface.id
    surface.delete()

    warnings = _restore_from_saved_snapshot(manager, graph, snapshot, deps)

    restored = graph.agent_node_list.first()
    assert list(restored.surface_list.values_list("id", flat=True)) == [
        surviving_surface.id
    ]

    surface_dropped_warnings = [w for w in warnings if w["type"] == "surface_dropped"]
    assert len(surface_dropped_warnings) == 1
    assert surface_dropped_warnings[0]["node_name"] == "agent_node"
    assert surface_dropped_warnings[0]["node_id"] == agent_node.id
    assert surface_dropped_warnings[0]["missing_id"] == deleted_surface_id


@pytest.mark.django_db
def test_restore_warns_and_drops_task_node_surface_when_deleted(
    manager, graph, surface
):
    from tables.models import TaskNode

    task_node = TaskNode.objects.create(graph=graph, node_name="task_node")
    task_node.surface_list.set([surface])
    snapshot = manager.create_snapshot(graph)
    deps = manager.collect_dependencies(graph)
    surface.delete()

    warnings = _restore_from_saved_snapshot(manager, graph, snapshot, deps)

    restored = graph.task_node_list.first()
    assert list(restored.surface_list.values_list("id", flat=True)) == []

    surface_dropped_warnings = [w for w in warnings if w["type"] == "surface_dropped"]
    assert len(surface_dropped_warnings) == 1
    assert surface_dropped_warnings[0]["node_name"] == "task_node"
    assert surface_dropped_warnings[0]["node_id"] == task_node.id


@pytest.mark.django_db
def test_restore_warns_and_drops_agent_node_inline_python_tool_when_deleted(
    manager, graph, python_code, python_code_tool
):
    from agents.models import AgentInlineSurface, AgentInlineSurfacePythonTool
    from tables.models import AgentNode, PythonCodeTool

    surviving_tool = PythonCodeTool.objects.create(
        name="SurvivingTool",
        description="Surviving PythonCodeTool",
        variables=[],
        python_code=python_code,
        favorite=False,
        built_in=False,
    )
    agent_node = AgentNode.objects.create(graph=graph, node_name="agent_node")
    inline_surface = AgentInlineSurface.objects.create(agent_node=agent_node)
    AgentInlineSurfacePythonTool.objects.create(
        agent_inline_surface=inline_surface,
        python_tool=python_code_tool,
        mode="allow",
    )
    AgentInlineSurfacePythonTool.objects.create(
        agent_inline_surface=inline_surface,
        python_tool=surviving_tool,
        mode="allow",
    )
    snapshot = manager.create_snapshot(graph)
    deps = manager.collect_dependencies(graph)
    deleted_tool_id = python_code_tool.id
    python_code_tool.delete()

    warnings = _restore_from_saved_snapshot(manager, graph, snapshot, deps)

    restored = graph.agent_node_list.first()
    restored_tool_ids = list(
        restored.inline_surface.python_tools.values_list("python_tool_id", flat=True)
    )
    assert restored_tool_ids == [surviving_tool.id]

    tool_dropped_warnings = [w for w in warnings if w["type"] == "inline_tool_dropped"]
    assert len(tool_dropped_warnings) == 1
    assert tool_dropped_warnings[0]["node_name"] == "agent_node"
    assert tool_dropped_warnings[0]["node_id"] == agent_node.id
    assert tool_dropped_warnings[0]["missing_id"] == deleted_tool_id


@pytest.mark.django_db
def test_restore_warns_and_drops_task_node_inline_mcp_tool_when_deleted(
    manager, graph, mcp_tool
):
    from agents.models import InlineSurface, InlineSurfaceMcpTool
    from tables.models import TaskNode

    task_node = TaskNode.objects.create(graph=graph, node_name="task_node")
    inline_surface = InlineSurface.objects.create(task_node=task_node)
    InlineSurfaceMcpTool.objects.create(
        inline_surface=inline_surface,
        mcp_tool=mcp_tool,
        mode="allow",
    )
    snapshot = manager.create_snapshot(graph)
    deps = manager.collect_dependencies(graph)
    deleted_mcp_tool_id = mcp_tool.id
    mcp_tool.delete()

    warnings = _restore_from_saved_snapshot(manager, graph, snapshot, deps)

    restored = graph.task_node_list.first()
    restored_tool_ids = list(
        restored.inline_surface.mcp_tools.values_list("mcp_tool_id", flat=True)
    )
    assert restored_tool_ids == []

    tool_dropped_warnings = [w for w in warnings if w["type"] == "inline_tool_dropped"]
    assert len(tool_dropped_warnings) == 1
    assert tool_dropped_warnings[0]["node_name"] == "task_node"
    assert tool_dropped_warnings[0]["node_id"] == task_node.id
    assert tool_dropped_warnings[0]["missing_id"] == deleted_mcp_tool_id


@pytest.mark.django_db
def test_restore_produces_no_warnings_when_agent_task_node_deps_all_present(
    manager, graph, agent_definition, surface, python_code_tool, mcp_tool
):
    from agents.models import (
        AgentInlineSurface,
        AgentInlineSurfacePythonTool,
        AgentInlineSurfaceMcpTool,
    )
    from tables.models import AgentNode, TaskNode

    agent_node = AgentNode.objects.create(
        graph=graph, node_name="agent_node", agent_definition=agent_definition
    )
    agent_node.surface_list.set([surface])
    inline_surface = AgentInlineSurface.objects.create(agent_node=agent_node)
    AgentInlineSurfacePythonTool.objects.create(
        agent_inline_surface=inline_surface,
        python_tool=python_code_tool,
        mode="allow",
    )
    AgentInlineSurfaceMcpTool.objects.create(
        agent_inline_surface=inline_surface,
        mcp_tool=mcp_tool,
        mode="allow",
    )
    TaskNode.objects.create(
        graph=graph, node_name="task_node", agent_definition=agent_definition
    )
    snapshot = manager.create_snapshot(graph)
    deps = manager.collect_dependencies(graph)

    warnings = _restore_from_saved_snapshot(manager, graph, snapshot, deps)

    assert warnings == []
    restored_agent_node = graph.agent_node_list.first()
    assert restored_agent_node.agent_definition_id == agent_definition.id
    assert list(restored_agent_node.surface_list.values_list("id", flat=True)) == [
        surface.id
    ]
