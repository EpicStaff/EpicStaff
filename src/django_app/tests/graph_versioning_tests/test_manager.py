"""Layer 2 tests: GraphVersioningManager."""

import pytest

from tables.graph_versioning.manager import GraphVersioningManager
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.constants import NODE_MAPPING_KEY
from tables.models import Graph, Edge, CrewNode, StartNode, GraphOrganization
from tests.fixtures import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Group A: filter_snapshot — pure dict logic, no DB
# ---------------------------------------------------------------------------


def test_filter_snapshot_skips_crew_node_when_crew_missing(manager, crew_node_dict):
    snapshot = {"nodes": [crew_node_dict], "edge_list": [], "conditional_edge_list": []}
    missing = {EntityType.CREW.value: [crew_node_dict["crew"]]}

    filtered, warnings = manager.filter_snapshot(snapshot, missing)

    assert filtered["nodes"] == []
    assert len(warnings) == 1
    assert warnings[0]["type"] == "node_skipped"


def test_filter_snapshot_keeps_crew_node_when_crew_available(manager, crew_node_dict):
    snapshot = {"nodes": [crew_node_dict], "edge_list": [], "conditional_edge_list": []}
    missing = {}

    filtered, warnings = manager.filter_snapshot(snapshot, missing)

    assert len(filtered["nodes"]) == 1
    assert filtered["nodes"][0]["id"] == crew_node_dict["id"]
    assert warnings == []


def test_filter_snapshot_drops_edge_to_skipped_node(
    manager, crew_node_dict, start_node_dict
):
    snapshot = {
        "nodes": [start_node_dict, crew_node_dict],
        "edge_list": [
            {
                "start_node_id": start_node_dict["id"],
                "end_node_id": crew_node_dict["id"],
            }
        ],
        "conditional_edge_list": [],
    }
    missing = {EntityType.CREW.value: [crew_node_dict["crew"]]}

    filtered, warnings = manager.filter_snapshot(snapshot, missing)

    assert filtered["edge_list"] == []
    warning_types = [w["type"] for w in warnings]
    assert "edge_dropped" in warning_types


def test_filter_snapshot_drops_edge_from_skipped_node(
    manager, crew_node_dict, start_node_dict
):
    # edge goes crew→start; crew is skipped
    snapshot = {
        "nodes": [start_node_dict, crew_node_dict],
        "edge_list": [
            {
                "start_node_id": crew_node_dict["id"],
                "end_node_id": start_node_dict["id"],
            }
        ],
        "conditional_edge_list": [],
    }
    missing = {EntityType.CREW.value: [crew_node_dict["crew"]]}

    filtered, warnings = manager.filter_snapshot(snapshot, missing)

    assert filtered["edge_list"] == []
    warning_types = [w["type"] for w in warnings]
    assert "edge_dropped" in warning_types


def test_filter_snapshot_drops_conditional_edge_from_skipped_node(
    manager, crew_node_dict, start_node_dict
):
    snapshot = {
        "nodes": [start_node_dict, crew_node_dict],
        "edge_list": [],
        "conditional_edge_list": [
            {"source_node_id": crew_node_dict["id"], "condition": "x > 0"}
        ],
    }
    missing = {EntityType.CREW.value: [crew_node_dict["crew"]]}

    filtered, warnings = manager.filter_snapshot(snapshot, missing)

    assert filtered["conditional_edge_list"] == []
    edge_dropped_warnings = [w for w in warnings if w["type"] == "edge_dropped"]
    assert len(edge_dropped_warnings) == 1
    assert "Conditional edge" in edge_dropped_warnings[0]["reason"]


def test_filter_snapshot_nulls_fk_for_code_agent_node(manager, code_agent_node_dict):
    # code_agent_node_dict has llm_config; llm_config is missing → FK nulled, not skipped
    snapshot = {
        "nodes": [code_agent_node_dict],
        "edge_list": [],
        "conditional_edge_list": [],
    }
    missing = {EntityType.LLM_CONFIG.value: [code_agent_node_dict["llm_config"]]}

    filtered, warnings = manager.filter_snapshot(snapshot, missing)

    assert len(filtered["nodes"]) == 1
    assert filtered["nodes"][0]["llm_config"] is None
    fk_nulled_warnings = [w for w in warnings if w["type"] == "fk_nulled"]
    assert len(fk_nulled_warnings) == 1


def test_filter_snapshot_no_warnings_when_all_deps_present(manager, crew_node_dict):
    snapshot = {"nodes": [crew_node_dict], "edge_list": [], "conditional_edge_list": []}
    missing = {}

    filtered, warnings = manager.filter_snapshot(snapshot, missing)

    assert warnings == []
    assert len(filtered["nodes"]) == 1


def test_filter_snapshot_does_not_mutate_input(manager, crew_node_dict):
    original_crew_value = crew_node_dict["crew"]
    snapshot = {"nodes": [crew_node_dict], "edge_list": [], "conditional_edge_list": []}
    missing = {EntityType.CREW.value: [crew_node_dict["crew"]]}

    manager.filter_snapshot(snapshot, missing)

    assert crew_node_dict["crew"] == original_crew_value


def test_filter_snapshot_clears_decision_table_default_next_node_id(
    manager, crew_node_dict, make_decision_table_node
):
    decision_node = make_decision_table_node(default_next=crew_node_dict["id"])
    snapshot = {
        "nodes": [crew_node_dict, decision_node],
        "edge_list": [],
        "conditional_edge_list": [],
    }
    missing = {EntityType.CREW.value: [crew_node_dict["crew"]]}

    filtered, warnings = manager.filter_snapshot(snapshot, missing)

    dt_nodes = [
        n for n in filtered["nodes"] if n["node_type"] == NodeType.DECISION_TABLE_NODE
    ]
    assert len(dt_nodes) == 1
    assert dt_nodes[0]["default_next_node_id"] is None
    ref_cleared = [w for w in warnings if w["type"] == "decision_table_ref_cleared"]
    assert len(ref_cleared) == 1


def test_filter_snapshot_clears_decision_table_next_error_node_id(
    manager, crew_node_dict, make_decision_table_node
):
    decision_node = make_decision_table_node(next_error=crew_node_dict["id"])
    snapshot = {
        "nodes": [crew_node_dict, decision_node],
        "edge_list": [],
        "conditional_edge_list": [],
    }
    missing = {EntityType.CREW.value: [crew_node_dict["crew"]]}

    filtered, warnings = manager.filter_snapshot(snapshot, missing)

    dt_nodes = [
        n for n in filtered["nodes"] if n["node_type"] == NodeType.DECISION_TABLE_NODE
    ]
    assert dt_nodes[0]["next_error_node_id"] is None
    ref_cleared = [w for w in warnings if w["type"] == "decision_table_ref_cleared"]
    assert len(ref_cleared) == 1


def test_filter_snapshot_clears_decision_table_condition_group_next_node_id(
    manager, crew_node_dict, make_decision_table_node
):
    decision_node = make_decision_table_node(
        condition_groups=[{"group_name": "g1", "next_node_id": crew_node_dict["id"]}]
    )
    snapshot = {
        "nodes": [crew_node_dict, decision_node],
        "edge_list": [],
        "conditional_edge_list": [],
    }
    missing = {EntityType.CREW.value: [crew_node_dict["crew"]]}

    filtered, warnings = manager.filter_snapshot(snapshot, missing)

    dt_nodes = [
        n for n in filtered["nodes"] if n["node_type"] == NodeType.DECISION_TABLE_NODE
    ]
    assert dt_nodes[0]["condition_groups"][0]["next_node_id"] is None
    ref_cleared = [w for w in warnings if w["type"] == "decision_table_ref_cleared"]
    assert len(ref_cleared) == 1
    assert "condition_groups[g1]" in ref_cleared[0]["field"]


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
def test_validate_dependencies_all_available(manager, crew, llm_config):
    dependencies = {
        EntityType.CREW.value: [crew.id],
        EntityType.LLM_CONFIG.value: [llm_config.id],
    }

    result = manager.validate_dependencies(dependencies)

    assert crew.id in result["available"][EntityType.CREW.value]
    assert llm_config.id in result["available"][EntityType.LLM_CONFIG.value]
    assert result["missing"][EntityType.CREW.value] == []
    assert result["missing"][EntityType.LLM_CONFIG.value] == []


@pytest.mark.django_db
def test_validate_dependencies_all_missing(manager):
    dependencies = {EntityType.CREW.value: [99998, 99999]}

    result = manager.validate_dependencies(dependencies)

    assert result["available"][EntityType.CREW.value] == []
    assert set(result["missing"][EntityType.CREW.value]) == {99998, 99999}


@pytest.mark.django_db
def test_validate_dependencies_mixed_available_and_missing(manager, crew):
    dependencies = {EntityType.CREW.value: [crew.id, 99999]}

    result = manager.validate_dependencies(dependencies)

    assert crew.id in result["available"][EntityType.CREW.value]
    assert 99999 in result["missing"][EntityType.CREW.value]


@pytest.mark.django_db
def test_validate_dependencies_filters_none_ids(manager, crew):
    dependencies = {EntityType.CREW.value: [crew.id, None, None]}

    result = manager.validate_dependencies(dependencies)

    assert crew.id in result["available"][EntityType.CREW.value]
    assert result["missing"][EntityType.CREW.value] == []


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
def test_collect_dependencies_with_crew_node(manager, graph, crew):
    from tables.models import CrewNode

    CrewNode.objects.create(graph=graph, node_name="cn", crew=crew)

    result = manager.collect_dependencies(graph)

    assert EntityType.CREW.value in result
    assert crew.id in result[EntityType.CREW.value]


# ---------------------------------------------------------------------------
# Group E: wipe & update graph — DB tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_wipe_graph_children_removes_crew_nodes(manager, graph, crew):
    from tables.models import CrewNode

    CrewNode.objects.create(graph=graph, node_name="wipe_test", crew=crew)
    assert graph.crew_node_list.count() == 1

    manager._wipe_graph_children(graph)

    assert graph.crew_node_list.count() == 0


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
        EntityType.CREW.value: [10, 20],
        EntityType.LLM_CONFIG.value: [5],
    }

    id_mapper = manager._build_identity_id_mapper(available_deps)

    # Identity: old_id == new_id
    assert id_mapper.get(EntityType.CREW, 10) == 10
    assert id_mapper.get(EntityType.CREW, 20) == 20
    assert id_mapper.get(EntityType.LLM_CONFIG, 5) == 5
    # was_created=False because deps already existed in DB
    assert id_mapper.was_created(EntityType.CREW, 10) is False


def test_build_identity_id_mapper_skips_unknown_entity_types(manager):
    available_deps = {
        "UnknownEntityType": [1, 2, 3],
    }

    id_mapper = manager._build_identity_id_mapper(available_deps)

    # No mapping should be created for unknown types
    assert not id_mapper.has_mapping("UnknownEntityType", 1)


@pytest.mark.django_db
def test_apply_snapshot_to_graph_round_trip(manager, graph, crew):
    from tables.models import CrewNode

    CrewNode.objects.create(graph=graph, node_name="original_cn", crew=crew)
    snapshot = manager.create_snapshot(graph)
    available_deps = {EntityType.CREW.value: [crew.id]}

    result = manager.apply_snapshot_to_graph(graph, snapshot, available_deps)

    # Method returns an IDMapper instance
    assert isinstance(result, IDMapper)
    # Graph still has exactly one CrewNode after wipe + recreate
    assert graph.crew_node_list.count() == 1
    # Recreated node references the same crew
    recreated = graph.crew_node_list.first()
    assert recreated.crew_id == crew.id


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
def test_create_graph_from_snapshot_recreates_crew_node(
    manager, graph, crew, default_org
):
    CrewNode.objects.create(graph=graph, node_name="cn", crew=crew)
    snapshot = manager.create_snapshot(graph)
    available_deps = {EntityType.CREW.value: [crew.id]}

    new_graph, _ = manager.create_graph_from_snapshot(
        snapshot, available_deps=available_deps, version_name="v1"
    )

    assert new_graph.crew_node_list.count() == 1
    assert new_graph.crew_node_list.first().crew_id == crew.id


@pytest.mark.django_db
def test_create_graph_from_snapshot_node_mapper_maps_old_to_new_node_id(
    manager, graph, crew, default_org
):
    CrewNode.objects.create(graph=graph, node_name="cn", crew=crew)
    snapshot = manager.create_snapshot(graph)
    available_deps = {EntityType.CREW.value: [crew.id]}

    crew_node_entry = next(
        n for n in snapshot["nodes"] if n["node_type"] == NodeType.CREW_NODE
    )
    old_node_id = crew_node_entry["id"]

    new_graph, node_mapper = manager.create_graph_from_snapshot(
        snapshot, available_deps=available_deps, version_name="v1"
    )

    new_crew_node = new_graph.crew_node_list.first()
    assert node_mapper.get(NODE_MAPPING_KEY, old_node_id) == new_crew_node.id


@pytest.mark.django_db
def test_create_graph_from_snapshot_recreates_edge_with_remapped_node_ids(
    manager, graph, crew, default_org
):
    start_node = StartNode.objects.create(graph=graph, variables={})
    crew_node = CrewNode.objects.create(graph=graph, node_name="cn", crew=crew)
    Edge.objects.create(
        graph=graph,
        start_node_id=start_node.id,
        end_node_id=crew_node.id,
    )
    snapshot = manager.create_snapshot(graph)
    available_deps = {EntityType.CREW.value: [crew.id]}

    new_graph, _ = manager.create_graph_from_snapshot(
        snapshot, available_deps=available_deps, version_name="v1"
    )

    assert new_graph.edge_list.count() == 1
    new_edge = new_graph.edge_list.first()
    original_node_ids = {start_node.id, crew_node.id}
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
