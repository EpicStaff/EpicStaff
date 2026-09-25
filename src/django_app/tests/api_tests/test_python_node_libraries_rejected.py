"""Saving a python node with a non-PEP-508 library entry returns HTTP 400."""

import pytest
from rest_framework.test import APIClient

from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from tables.models import PythonCode
from tables.models.graph_models import Graph, PythonNode

NODE_CODE = "def main(**kwargs):\n    return 1\n"


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org Libraries")


@pytest.fixture
def admin_client(db, django_user_model, org):
    role = Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(
        email="libraries_admin@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def graph(org):
    return Graph.objects.create(name="Libraries flow", org=org)


@pytest.fixture
def python_node(graph):
    python_code = PythonCode.objects.create(code=NODE_CODE, entrypoint="main")
    return PythonNode.objects.create(graph=graph, node_name="installer", python_code=python_code)


def _save_payload(graph: Graph, python_node: PythonNode, libraries: list[str]) -> dict:
    return {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "id": python_node.id,
                "graph": graph.id,
                "node_name": "installer",
                "python_code": {
                    "code": NODE_CODE,
                    "entrypoint": "main",
                    "libraries": libraries,
                    "global_kwargs": {},
                },
            }
        ],
    }


@pytest.mark.django_db
class TestPythonNodeLibrariesValidation:
    @pytest.mark.parametrize(
        "entry",
        ["/proc/self", "/", "file:///etc", "name @ https://evil.example.com/a.whl"],
    )
    def test_rejects_paths_and_direct_references(self, admin_client, graph, python_node, entry):
        response = admin_client.post(
            f"/api/graphs/{graph.id}/save/",
            _save_payload(graph, python_node, [entry]),
            format="json",
        )

        assert response.status_code == 400, response.json()

        python_node.python_code.refresh_from_db()
        assert python_node.python_code.libraries == ""

    def test_accepts_valid_pip_specs(self, admin_client, graph, python_node):
        response = admin_client.post(
            f"/api/graphs/{graph.id}/save/",
            _save_payload(graph, python_node, ["requests==2.31.0", "numpy>=1,<2"]),
            format="json",
        )

        assert response.status_code == 200, response.json()

        python_node.python_code.refresh_from_db()
        assert python_node.python_code.get_libraries_list() == [
            "requests==2.31.0",
            "numpy>=1,<2",
        ]
