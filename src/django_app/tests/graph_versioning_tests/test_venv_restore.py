"""Regression tests: restoring a GraphVersion whose nodes carry a custom venv used
to 500 (`remap_python_code_venv` raised `ValueError`) because `validate_dependencies`
had no `EntityType.VENV` entry at all."""

import pytest

from proxies.sandbox.models import SandboxVenvBinding
from tables.import_export.enums import EntityType
from tables.models import GraphVersion, PythonCode, PythonNode
from tables.models.graph_models import ClassificationDecisionTableNode
from tests.fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _restore_from_saved_snapshot(manager, graph, snapshot, deps):
    """Mirrors GraphVersioningService._prepare: validate, recover venv ids the
    snapshot references directly, filter, then apply."""
    deps_validation = manager.validate_dependencies(deps, graph.org_id)
    manager.resolve_venv_availability(snapshot, deps_validation["available"], graph.org_id)
    filtered_snapshot, warnings = manager.filter_snapshot(
        snapshot, deps_validation["missing"], deps_validation["available"]
    )
    manager.apply_snapshot_to_graph(graph, filtered_snapshot, deps_validation["available"])
    return warnings


def _venv_ref_cleared_warnings(warnings):
    return [w for w in warnings if w["type"] == "venv_ref_cleared"]


@pytest.mark.django_db
def test_restore_keeps_python_node_on_live_in_org_venv(manager, graph, default_org):
    venv = SandboxVenvBinding.objects.create(org_id=default_org.id, resource_id="1")
    python_code = PythonCode.objects.create(code="def main(): pass", venv=venv)
    PythonNode.objects.create(graph=graph, python_code=python_code, node_name="py")

    snapshot = manager.create_snapshot(graph)
    deps = manager.collect_dependencies(graph)
    assert deps.get(EntityType.VENV.value) == [venv.id]

    warnings = _restore_from_saved_snapshot(manager, graph, snapshot, deps)

    restored = graph.python_node_list.get(node_name="py")
    assert restored.python_code.venv_id == venv.id
    assert _venv_ref_cleared_warnings(warnings) == []


@pytest.mark.django_db
def test_restore_clears_venv_belonging_to_another_org(manager, graph, default_org, beta):
    foreign_venv = SandboxVenvBinding.objects.create(org_id=beta.id, resource_id="1")
    python_code = PythonCode.objects.create(code="def main(): pass", venv=foreign_venv)
    python_node = PythonNode.objects.create(
        graph=graph, python_code=python_code, node_name="py"
    )

    snapshot = manager.create_snapshot(graph)
    deps = manager.collect_dependencies(graph)
    assert deps.get(EntityType.VENV.value) == [foreign_venv.id]

    warnings = _restore_from_saved_snapshot(manager, graph, snapshot, deps)

    restored = graph.python_node_list.get(node_name="py")
    assert restored.python_code.venv_id is None

    cleared = _venv_ref_cleared_warnings(warnings)
    assert len(cleared) == 1
    assert cleared[0]["node_id"] == python_node.id


@pytest.mark.django_db
def test_restore_clears_both_cdt_slots_independently(manager, graph, default_org, beta):
    foreign_venv = SandboxVenvBinding.objects.create(org_id=beta.id, resource_id="1")
    pre_code = PythonCode.objects.create(code="def main(): return 1", venv=foreign_venv)
    post_code = PythonCode.objects.create(code="def main(): return 2", venv=foreign_venv)
    cdt_node = ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="cdt", pre_python_code=pre_code, post_python_code=post_code
    )

    snapshot = manager.create_snapshot(graph)
    deps = manager.collect_dependencies(graph)

    warnings = _restore_from_saved_snapshot(manager, graph, snapshot, deps)

    restored = graph.classification_decision_table_node_list.get(node_name="cdt")
    assert restored.pre_python_code.venv_id is None
    assert restored.post_python_code.venv_id is None

    cleared = _venv_ref_cleared_warnings(warnings)
    assert len(cleared) == 2
    assert {w["node_id"] for w in cleared} == {cdt_node.id}


@pytest.mark.django_db
def test_restore_recovers_venv_missing_from_recorded_dependencies(manager, graph, default_org):
    """Pre-venv-collection version: `dependencies` has no "Venv" key, but the node
    carries a real id that must still resolve against its own org."""
    venv = SandboxVenvBinding.objects.create(org_id=default_org.id, resource_id="1")
    python_code = PythonCode.objects.create(code="def main(): pass", venv=venv)
    PythonNode.objects.create(graph=graph, python_code=python_code, node_name="py")

    snapshot = manager.create_snapshot(graph)
    deps = manager.collect_dependencies(graph)
    deps.pop(EntityType.VENV.value, None)

    warnings = _restore_from_saved_snapshot(manager, graph, snapshot, deps)

    restored = graph.python_node_list.get(node_name="py")
    assert restored.python_code.venv_id == venv.id
    assert _venv_ref_cleared_warnings(warnings) == []


@pytest.mark.django_db
def test_preview_v4_snapshot_clears_synthetic_venv_instead_of_matching_a_real_binding(
    service, graph, default_org
):
    """A v4 snapshot (`libraries`, no `venv`) converts through `v4_to_v5`, which
    invents venv ids starting at 1 — must never collide with a real binding of
    the same id. Goes through the real service pipeline, not a shortcut."""
    SandboxVenvBinding.objects.create(id=1, org_id=default_org.id, resource_id="unrelated-venv")

    version = GraphVersion.objects.create(
        graph=graph,
        name="legacy-v4",
        snapshot={
            "version": 4,
            "nodes": [
                {
                    "id": 1,
                    "node_type": "PythonNode",
                    "node_name": "py",
                    "python_code": {
                        "code": "def main(): pass",
                        "entrypoint": "main",
                        "global_kwargs": {},
                        "libraries": "requests==2.31.0",
                    },
                }
            ],
            "edge_list": [],
        },
        dependencies={},
    )

    preview = service.preview_version(version)

    restored_node = preview["snapshot"]["nodes"][0]
    assert restored_node["python_code"]["venv"] is None
    assert _venv_ref_cleared_warnings(preview["warnings"])
