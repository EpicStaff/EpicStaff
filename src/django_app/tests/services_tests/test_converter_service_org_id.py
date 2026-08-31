"""
EST-3285: authoritative org_id resolution for sandbox callback tools.

main's RBAC merge made org-scoped Django endpoints (e.g. GET /sessions/<id>/,
/schedule-trigger-nodes/) require X-Organization-Id. Sandbox callback tools
(fanout_tool, subflow_tool, schedule_manager_tool) call back into the API with
only X-Api-Key, so their converter-produced PythonCodeData must carry the
running session's authoritative org_id (read from Graph.org_id — never from
the optional GraphOrganization storage-prefix table, and never from agent
input) so it can be injected into the sandbox as `globals()["org_id"]`.
"""

import pytest

from tables.models import PythonCode, PythonCodeTool, PythonCodeToolConfig, Graph
from tables.models.rbac_models import Organization
from tables.services.converter_service import ConverterService


@pytest.fixture
def converter() -> ConverterService:
    return ConverterService()


@pytest.mark.django_db
def test_resolve_authoritative_org_id_returns_graph_org_id(converter):
    org = Organization.objects.create(name="Org A")
    graph = Graph.objects.create(name="g1", org=org)

    resolved = converter._resolve_authoritative_org_id_for_graph(graph.pk)

    assert resolved == org.pk


@pytest.mark.django_db
def test_resolve_authoritative_org_id_none_for_missing_graph(converter):
    resolved = converter._resolve_authoritative_org_id_for_graph(999_999)

    assert resolved is None


@pytest.mark.django_db
def test_convert_python_code_tool_to_pydantic_populates_org_id_from_graph(converter):
    """org_id must come from Graph.org_id, NOT from the separate
    GraphOrganization storage-prefix table (which is left untouched/empty
    here to prove the two are independent)."""
    org = Organization.objects.create(name="Org B")
    graph = Graph.objects.create(name="g2", org=org)

    code = PythonCode.objects.create(code="def main(**kw): return kw")
    tool = PythonCodeTool.objects.create(
        name="tool-b",
        description="desc",
        python_code=code,
        org=org,
        variables=[],
    )

    data = converter.convert_python_code_tool_to_pydantic(
        tool, graph_id=graph.pk, session_id=1
    )

    assert data.python_code.org_id == org.pk
    # storage_org_prefix comes from GraphOrganization, which was never
    # populated in this test — confirms org_id is resolved independently.
    assert data.python_code.storage_org_prefix is None


@pytest.mark.django_db
def test_convert_python_code_tool_to_pydantic_org_id_none_without_graph_id(converter):
    org = Organization.objects.create(name="Org C")
    code = PythonCode.objects.create(code="def main(**kw): return kw")
    tool = PythonCodeTool.objects.create(
        name="tool-c", description="desc", python_code=code, org=org, variables=[]
    )

    data = converter.convert_python_code_tool_to_pydantic(tool, graph_id=None)

    assert data.python_code.org_id is None


@pytest.mark.django_db
def test_convert_python_code_tool_config_to_pydantic_populates_org_id(converter):
    org = Organization.objects.create(name="Org D")
    graph = Graph.objects.create(name="g3", org=org)

    code = PythonCode.objects.create(code="def main(**kw): return kw")
    tool = PythonCodeTool.objects.create(
        name="tool-d", description="desc", python_code=code, org=org, variables=[]
    )
    tool_config = PythonCodeToolConfig.objects.create(
        name="cfg-d", tool=tool, org=org, configuration={}
    )

    data = converter.convert_python_code_tool_config_to_pydantic(
        tool_config, graph_id=graph.pk, session_id=2
    )

    assert data.python_code.org_id == org.pk


@pytest.mark.django_db
def test_convert_python_code_tool_to_pydantic_honors_storage_overrides_without_graph(
    converter,
):
    """No graph_id at all (e.g. a realtime agent-definition session) --
    storage_allowed_paths/storage_org_prefix/org_id must still resolve when
    explicit overrides are supplied, instead of silently staying None."""
    org = Organization.objects.create(name="Org F")
    code = PythonCode.objects.create(code="def main(**kw): return kw")
    tool = PythonCodeTool.objects.create(
        name="tool-f",
        description="desc",
        python_code=code,
        org=org,
        variables=[],
        use_storage=True,
    )

    data = converter.convert_python_code_tool_to_pydantic(
        tool,
        graph_id=None,
        storage_allowed_paths_override=["notes/report.txt"],
        storage_org_prefix_override=f"org_{org.pk}",
        org_id_override=org.pk,
    )

    assert data.python_code.storage_allowed_paths == ["notes/report.txt"]
    assert data.python_code.storage_org_prefix == f"org_{org.pk}"
    assert data.python_code.org_id == org.pk


@pytest.mark.django_db
def test_convert_python_node_to_pydantic_populates_org_id(converter):
    from tables.models import PythonNode

    org = Organization.objects.create(name="Org E")
    graph = Graph.objects.create(name="g4", org=org)
    code = PythonCode.objects.create(code="def main(**kw): return kw")
    node = PythonNode.objects.create(graph=graph, python_code=code)

    data = converter.convert_python_node_to_pydantic(node, graph_id=graph.pk)

    assert data.python_code.org_id == org.pk
