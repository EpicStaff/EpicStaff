"""A PythonCode's declared secrets are readable over the API, names only."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from tables.models import PythonCode
from tables.models.graph_models import Graph, PythonNode
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_service


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org DeclRead")


@pytest.fixture
def admin_client(db, django_user_model, org):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="declread_admin@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def secret(org):
    return secret_service.create(text="sk-declread", org=org, name="DECLREAD_KEY")


@pytest.fixture
def graph(org):
    return Graph.objects.create(name="DeclRead flow", org=org)


@pytest.fixture
def python_node(graph, secret):
    python_code = PythonCode.objects.create(
        code='def main(**kwargs):\n    return get_secret("DECLREAD_KEY")\n',
        entrypoint="main",
    )
    python_code.secrets.set([secret])
    return PythonNode.objects.create(
        graph=graph, node_name="reader", python_code=python_code
    )


@pytest.mark.django_db
class TestDeclarationIsReadable:
    def test_graph_detail_returns_declared_names(
        self, admin_client, graph, python_node, secret
    ):
        response = admin_client.get(f"/api/graphs/{graph.id}/")

        assert response.status_code == 200
        node = response.json()["python_node_list"][0]
        assert node["python_code"]["secrets"] == [
            {"id": secret.id, "name": "DECLREAD_KEY"}
        ]

    def test_no_part_of_the_value_is_exposed(self, admin_client, graph, python_node):
        response = admin_client.get(f"/api/graphs/{graph.id}/")

        declared = response.json()["python_node_list"][0]["python_code"]["secrets"][0]
        assert set(declared) == {"id", "name"}

    def test_undeclared_code_returns_an_empty_list(self, admin_client, graph):
        python_code = PythonCode.objects.create(
            code="def main(**kwargs):\n    return 1\n"
        )
        PythonNode.objects.create(
            graph=graph, node_name="plain", python_code=python_code
        )

        response = admin_client.get(f"/api/graphs/{graph.id}/")

        nodes = {n["node_name"]: n for n in response.json()["python_node_list"]}
        assert nodes["plain"]["python_code"]["secrets"] == []

    def test_secret_ids_stays_write_only(self, admin_client, graph, python_node):
        response = admin_client.get(f"/api/graphs/{graph.id}/")

        node = response.json()["python_node_list"][0]
        assert "secret_ids" not in node["python_code"]


@pytest.mark.django_db
class TestDeclarationReadDoesNotNPlusOne:
    def _add_python_node(self, graph, secret, name):
        python_code = PythonCode.objects.create(
            code='def main(**kwargs):\n    return get_secret("DECLREAD_KEY")\n',
            entrypoint="main",
        )
        python_code.secrets.set([secret])
        return PythonNode.objects.create(
            graph=graph, node_name=name, python_code=python_code
        )

    def test_query_count_is_flat_in_node_count(self, admin_client, graph, secret):
        self._add_python_node(graph, secret, "n1")
        with CaptureQueriesContext(connection) as one_node:
            admin_client.get(f"/api/graphs/{graph.id}/")

        for name in ("n2", "n3", "n4", "n5"):
            self._add_python_node(graph, secret, name)
        with CaptureQueriesContext(connection) as five_nodes:
            admin_client.get(f"/api/graphs/{graph.id}/")

        assert len(five_nodes) == len(one_node), (
            f"reading five declaring nodes cost {len(five_nodes)} queries against "
            f"{len(one_node)} for one — the declaration is not prefetched"
        )
