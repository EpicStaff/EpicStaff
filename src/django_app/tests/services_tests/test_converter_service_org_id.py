"""
Authoritative org_id resolution for sandbox callback tools.

main's RBAC merge made org-scoped Django endpoints (e.g. GET /sessions/<id>/,
/schedule-trigger-nodes/) require X-Organization-Id. Sandbox callback tools
(fanout_tool, subflow_tool, schedule_manager_tool) call back into the API with
only X-Api-Key, so their converter-produced PythonCodeData must carry the
running session's authoritative org_id (read from Graph.org_id — never from
the optional GraphOrganization storage-prefix table, and never from agent
input) so it can be injected into the sandbox as `globals()["org_id"]`.
"""

import pytest

from tables.models import Graph, PythonCode, PythonCodeTool, PythonCodeToolConfig, PythonNode
from rbac.models import Organization
from tables.services.converter_service import ConverterService


@pytest.fixture
def converter() -> ConverterService:
    return ConverterService()


def _tool(org):
    code = PythonCode.objects.create(code="def main(**kw): return kw")
    return PythonCodeTool.objects.create(
        name=f"tool-{org.pk}", description="desc", python_code=code, org=org, variables=[]
    )


CONVERSIONS = {
    "tool": lambda converter, org, graph_id: converter.convert_python_code_tool_to_pydantic(
        _tool(org), graph_id=graph_id, session_id=1
    ),
    "tool-config": lambda converter, org, graph_id: converter.convert_python_code_tool_config_to_pydantic(
        PythonCodeToolConfig.objects.create(name="cfg", tool=_tool(org), org=org, configuration={}),
        graph_id=graph_id,
        session_id=2,
    ),
    "python-node": lambda converter, org, graph_id: converter.convert_python_node_to_pydantic(
        PythonNode.objects.create(
            graph=Graph.objects.get(pk=graph_id),
            python_code=PythonCode.objects.create(code="def main(**kw): return kw"),
        ),
        graph_id=graph_id,
    ),
}


@pytest.mark.django_db
@pytest.mark.parametrize("conversion", list(CONVERSIONS))
def test_converted_code_carries_the_graphs_org_id(converter, conversion):
    """org_id must come from Graph.org_id, NOT from the separate GraphOrganization
    storage-prefix table (never populated here, so the prefix stays None)."""
    org = Organization.objects.create(name=f"Org {conversion}")
    # Push the graph id away from the org id, so reading the wrong column can't pass.
    Graph.objects.bulk_create(Graph(name=f"filler-{index}", org=org) for index in range(3))
    graph = Graph.objects.create(name=f"g-{conversion}", org=org)
    assert graph.pk != org.pk

    data = CONVERSIONS[conversion](converter, org, graph.pk)

    assert data.python_code.org_id == org.pk
    assert data.python_code.storage_org_prefix is None


@pytest.mark.django_db
@pytest.mark.parametrize("graph_id", [None, 999_999], ids=["no-graph", "unknown-graph"])
def test_code_without_a_resolvable_graph_carries_no_org_id(converter, graph_id):
    org = Organization.objects.create(name="Org C")

    data = converter.convert_python_code_tool_to_pydantic(_tool(org), graph_id=graph_id)

    assert data.python_code.org_id is None


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
