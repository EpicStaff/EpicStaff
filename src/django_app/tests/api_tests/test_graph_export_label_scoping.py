import pytest
from rest_framework.test import APIClient

from agents.models import AgentInlineSurface, AgentInlineSurfacePythonTool
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import Permission, ResourceType
from rbac.models.role import RolePermission
from tables.models import AgentNode, Graph
from tables.models.label_models import Label
from tables.models.python_models import PythonCode, PythonCodeTool


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def client_a(db, django_user_model, org_a):
    role = Role.objects.create(name="FlowExporter", org=org_a, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.FLOWS,
        permissions=int(Permission.CREATE | Permission.READ | Permission.EXPORT),
    )
    user = django_user_model.objects.create_user(
        email="flow_exporter_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


@pytest.fixture
def flow_using_shared_built_in_tool(org_a, org_b):
    """Org A flow using a built-in tool that carries labels from both orgs."""
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main", libraries="")
    tool = PythonCodeTool.objects.create(
        name="SharedBuiltIn", description="desc", python_code=code, org=None, built_in=True
    )
    label_a = Label.objects.create(name="OrgALabel", org=org_a, scope=Label.Scope.TOOL)
    label_b = Label.objects.create(name="OrgBLabel", org=org_b, scope=Label.Scope.TOOL)
    tool.labels.set([label_a, label_b])

    graph = Graph.objects.create(name="OrgAFlow", org=org_a)
    agent_node = AgentNode.objects.create(graph=graph, node_name="agent_node")
    inline_surface = AgentInlineSurface.objects.create(agent_node=agent_node)
    AgentInlineSurfacePythonTool.objects.create(
        agent_inline_surface=inline_surface, python_tool=tool, mode="allow"
    )
    return graph


@pytest.mark.django_db
def test_flow_export_does_not_leak_other_org_labels_on_shared_tool(
    client_a, flow_using_shared_built_in_tool
):
    response = client_a.get(f"/api/graphs/{flow_using_shared_built_in_tool.id}/export/")

    assert response.status_code == 200, response.content
    body = response.content.decode()
    assert "SharedBuiltIn" in body
    assert "OrgALabel" in body
    assert "OrgBLabel" not in body


@pytest.mark.django_db
def test_flow_bulk_export_does_not_leak_other_org_labels_on_shared_tool(
    client_a, flow_using_shared_built_in_tool
):
    response = client_a.post(
        "/api/graphs/bulk-export/",
        {"ids": [flow_using_shared_built_in_tool.id]},
        format="json",
    )

    assert response.status_code == 200, response.content
    body = response.content.decode()
    assert "SharedBuiltIn" in body
    assert "OrgALabel" in body
    assert "OrgBLabel" not in body
