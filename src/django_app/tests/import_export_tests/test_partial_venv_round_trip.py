"""Partial export-import cycle for nodes with custom virtual environments.

Tests that a node exported from one org with a custom venv can be imported into
another org, creating a new venv binding there with the same libraries. Re-importing
the same file detects and reuses the existing environment instead of creating a
duplicate.
"""

import pytest
from proxies.sandbox.models import SandboxVenvBinding

from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.models import Graph, PythonCode, PythonNode
from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.import_export_tests.venv_fakes import upstream_venv
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _python_node_with_code(graph, node_name, python_code):
    """Create a Python node with the given Python code."""
    return PythonNode.objects.create(graph=graph, node_name=node_name, python_code=python_code)


@pytest.fixture
def source_graph(acme):
    """A graph in org acme with a Python node using a custom venv."""
    return Graph.objects.create(name="source-flow", org=acme)


@pytest.fixture
def target_graph(beta):
    """A graph in org beta where we import nodes."""
    graph = Graph.objects.create(name="target-flow", org=beta)
    return graph


@pytest.mark.django_db
class TestPartialVenvRoundTrip:
    """Export a node with a custom venv and import it across organizations."""

    def test_node_with_venv_exports_and_imports_to_different_org(
        self, acme, beta, source_graph, target_graph, sandbox
    ):
        """Export node from org1 with custom venv, import into org2.

        The new import gets a fresh venv binding for org2 with the same libraries.
        """
        # Setup: create venv in acme and bind a node to it
        source_binding = upstream_venv(sandbox, acme, name="scraper-venv", venv_id=4711)
        python_code = PythonCode.objects.create(
            code="def main(): return 1", entrypoint="main", venv=source_binding
        )
        source_node = _python_node_with_code(source_graph, "scraper", python_code)

        # Export the node from acme
        export_result = GraphPartialExportService(entity_registry).export(
            [NodeRef(EntityType.PYTHON_NODE, source_node.id)],
            org_id=acme.id,
            policy=UNRESTRICTED_EXPORT_POLICY,
        )
        assert not export_result.has_errors
        export_data = export_result.data

        # Verify the export carries the venv
        assert len(export_data[EntityType.VENV]) == 1
        exported_venv = export_data[EntityType.VENV][0]
        assert exported_venv["name"] == "scraper-venv"
        assert exported_venv["libs"] == [{"name": "httpx", "specification": ">=0.28"}]

        # Import into beta: should create a new venv binding for beta
        partial_import_service = PartialImportService(entity_registry)
        result = partial_import_service.import_data(
            export_data, target_graph, org_id=beta.id
        )

        # The import should succeed and return unsaved content
        assert result.content
        imported_nodes = result.content["python_node_list"]
        assert len(imported_nodes) == 1
        imported_node = imported_nodes[0]

        # Verify the imported node references a new venv binding in beta
        new_venv_id = imported_node["python_code"]["venv_id"]
        assert new_venv_id is not None
        new_binding = SandboxVenvBinding.objects.get(pk=new_venv_id)
        assert new_binding.org_id == beta.id
        # The sandbox should have a venv for this binding with the same name and libs
        new_venv = sandbox.venvs[int(new_binding.resource_id)]
        assert new_venv["name"] == "scraper-venv"
        assert new_venv["libs"] == [{"name": "httpx", "specification": ">=0.28"}]

    def test_reimporting_same_file_reuses_existing_venv(
        self, acme, beta, source_graph, target_graph, sandbox, regular_user
    ):
        """Re-importing the same file into beta detects and reuses the existing venv.

        First import creates a venv in beta. Second import finds it (name and libs match)
        and attaches to the existing binding, not creating a new one.
        """
        # Setup: create venv in acme and bind a node to it
        source_binding = upstream_venv(sandbox, acme, name="scraper-venv", venv_id=4711)
        python_code = PythonCode.objects.create(
            code="def main(): return 1", entrypoint="main", venv=source_binding
        )
        source_node = _python_node_with_code(source_graph, "scraper", python_code)

        # Export the node from acme
        export_result = GraphPartialExportService(entity_registry).export(
            [NodeRef(EntityType.PYTHON_NODE, source_node.id)],
            org_id=acme.id,
            policy=UNRESTRICTED_EXPORT_POLICY,
        )
        export_data = export_result.data

        # First import: creates venv in beta
        partial_import_service = PartialImportService(entity_registry)
        result1 = partial_import_service.import_data(
            export_data, target_graph, org_id=beta.id, user=regular_user
        )
        first_imported_nodes = result1.content["python_node_list"]
        first_venv_id = first_imported_nodes[0]["python_code"]["venv_id"]
        first_binding = SandboxVenvBinding.objects.get(pk=first_venv_id)

        # Count venvs in beta before second import
        venv_count_before = SandboxVenvBinding.objects.filter(org_id=beta.id).count()

        # Second import: should detect and reuse the same venv
        # (We need a new target graph for this import since the first one is already
        # modified by the first import)
        target_graph2 = Graph.objects.create(name="target-flow-2", org=beta)
        result2 = partial_import_service.import_data(
            export_data, target_graph2, org_id=beta.id, user=regular_user
        )
        second_imported_nodes = result2.content["python_node_list"]
        second_venv_id = second_imported_nodes[0]["python_code"]["venv_id"]

        # The second import should have reused the venv, not created a new one
        assert second_venv_id == first_venv_id
        venv_count_after = SandboxVenvBinding.objects.filter(org_id=beta.id).count()
        assert venv_count_after == venv_count_before, "A duplicate venv was created"

        # Verify the reused binding is still the same
        reused_binding = SandboxVenvBinding.objects.get(pk=second_venv_id)
        assert reused_binding.id == first_binding.id

    def test_venv_is_created_in_sandbox_with_correct_name_and_libraries(
        self, acme, beta, source_graph, target_graph, sandbox
    ):
        """The imported venv in sandbox has the same name and libraries as the source."""
        # Setup: create venv in acme with specific libraries
        source_binding = upstream_venv(
            sandbox,
            acme,
            name="data-processor",
            libs=[
                {"name": "pandas", "specification": ">=2.0"},
                {"name": "numpy", "specification": ">=1.24"},
            ],
            venv_id=4711,
        )
        python_code = PythonCode.objects.create(
            code="def main(): return 1", entrypoint="main", venv=source_binding
        )
        source_node = _python_node_with_code(source_graph, "processor", python_code)

        # Export and import
        export_result = GraphPartialExportService(entity_registry).export(
            [NodeRef(EntityType.PYTHON_NODE, source_node.id)],
            org_id=acme.id,
            policy=UNRESTRICTED_EXPORT_POLICY,
        )
        export_data = export_result.data

        partial_import_service = PartialImportService(entity_registry)
        result = partial_import_service.import_data(
            export_data, target_graph, org_id=beta.id
        )

        # Verify the sandbox venv has the correct name and libraries
        imported_nodes = result.content["python_node_list"]
        new_venv_id = imported_nodes[0]["python_code"]["venv_id"]
        new_binding = SandboxVenvBinding.objects.get(pk=new_venv_id)
        new_venv = sandbox.venvs[int(new_binding.resource_id)]

        assert new_venv["name"] == "data-processor"
        assert len(new_venv["libs"]) == 2
        lib_names = {lib["name"] for lib in new_venv["libs"]}
        assert lib_names == {"pandas", "numpy"}
        lib_specs = {
            (lib["name"], lib["specification"]) for lib in new_venv["libs"]
        }
        expected = {("pandas", ">=2.0"), ("numpy", ">=1.24")}
        assert lib_specs == expected
