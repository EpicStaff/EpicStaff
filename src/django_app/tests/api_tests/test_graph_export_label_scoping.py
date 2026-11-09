import pytest

from agents.models import AgentInlineSurface, AgentInlineSurfacePythonTool
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import Permission, ResourceType
from rbac.models.role import RolePermission
from tables.models import AgentNode, Graph, TransferJob
from tables.models.label_models import Label
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.services.transfer_jobs.export_definitions import export_definition
from tables.services.transfer_jobs.job_service import TransferJobService
from tests.transfer_job_helpers import run_job


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def exporter_a(db, django_user_model, org_a):
    role = Role.objects.create(name="FlowExporter", org=org_a, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.FLOWS,
        permissions=int(Permission.CREATE | Permission.READ | Permission.EXPORT),
    )
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.TOOLS,
        permissions=int(Permission.READ | Permission.EXPORT),
    )
    user = django_user_model.objects.create_user(
        email="flow_exporter_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role)
    return user


@pytest.fixture
def flow_using_shared_built_in_tool(org_a, org_b):
    """Org A flow using a built-in tool that carries labels from both orgs."""
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
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
    exporter_a, org_a, flow_using_shared_built_in_tool
):
    job = TransferJobService().start_export(
        user=exporter_a,
        org_id=org_a.id,
        definition=export_definition(TransferJob.MainEntity.FLOW),
        validated_data={"ids": [flow_using_shared_built_in_tool.id], "include_knowledge": False},
    )

    exported = run_job(job.id)

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    body = exported.members["export.json"].decode()
    assert "SharedBuiltIn" in body
    assert "OrgALabel" in body
    assert "OrgBLabel" not in body
