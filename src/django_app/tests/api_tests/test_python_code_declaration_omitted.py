"""Omitting secret_ids on an update leaves the declaration alone and stays valid."""

import pytest
from rest_framework.test import APIClient

from tables.models import PythonCode
from tables.models.graph_models import Graph, PythonNode
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_service

DECLARING_CODE = 'def main(**kwargs):\n    return get_secret("OMIT_KEY")\n'
EDITED_CODE = 'def main(**kwargs):\n    return get_secret("OMIT_KEY") + 1\n'


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org Omit")


@pytest.fixture
def admin_client(db, django_user_model, org):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="omit_admin@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def secret(org):
    return secret_service.create(text="sk-omit", org=org, name="OMIT_KEY")


@pytest.fixture
def graph(org):
    return Graph.objects.create(name="Omit flow", org=org)


@pytest.fixture
def python_node(graph, secret):
    python_code = PythonCode.objects.create(code=DECLARING_CODE, entrypoint="main")
    python_code.secrets.set([secret])
    return PythonNode.objects.create(
        graph=graph, node_name="omitter", python_code=python_code
    )


@pytest.fixture
def non_declaring_python_node(graph, secret):
    python_code = PythonCode.objects.create(
        code="def main(**kwargs):\n    return 1\n", entrypoint="main"
    )
    python_code.secrets.set([secret])
    return PythonNode.objects.create(
        graph=graph, node_name="clearable", python_code=python_code
    )


@pytest.mark.django_db
class TestOmittingSecretIdsOnUpdate:
    def test_editing_code_without_resending_secret_ids_is_accepted(
        self, admin_client, graph, python_node
    ):
        payload = {
            "save_version": graph.save_version,
            "python_node_list": [
                {
                    "id": python_node.id,
                    "graph": graph.id,
                    "node_name": "omitter",
                    "python_code": {
                        "code": EDITED_CODE,
                        "entrypoint": "main",
                        "libraries": [],
                        "global_kwargs": {},
                    },
                }
            ],
        }

        response = admin_client.post(
            f"/api/graphs/{graph.id}/save/", payload, format="json"
        )

        assert response.status_code == 200, response.json()

    def test_the_declaration_survives_the_omission(
        self, admin_client, graph, python_node, secret
    ):
        payload = {
            "save_version": graph.save_version,
            "python_node_list": [
                {
                    "id": python_node.id,
                    "graph": graph.id,
                    "node_name": "omitter",
                    "python_code": {
                        "code": EDITED_CODE,
                        "entrypoint": "main",
                        "libraries": [],
                        "global_kwargs": {},
                    },
                }
            ],
        }

        admin_client.post(f"/api/graphs/{graph.id}/save/", payload, format="json")

        python_node.python_code.refresh_from_db()
        assert list(python_node.python_code.secrets.values_list("name", flat=True)) == [
            "OMIT_KEY"
        ]

    def test_sending_an_empty_list_still_clears_and_therefore_rejects(
        self, admin_client, graph, python_node
    ):
        payload = {
            "save_version": graph.save_version,
            "python_node_list": [
                {
                    "id": python_node.id,
                    "graph": graph.id,
                    "node_name": "omitter",
                    "python_code": {
                        "code": EDITED_CODE,
                        "entrypoint": "main",
                        "libraries": [],
                        "global_kwargs": {},
                        "secret_ids": [],
                    },
                }
            ],
        }

        response = admin_client.post(
            f"/api/graphs/{graph.id}/save/", payload, format="json"
        )

        assert response.status_code == 400

    def test_sending_an_empty_list_clears_the_declaration_when_legal(
        self, admin_client, graph, non_declaring_python_node
    ):
        payload = {
            "save_version": graph.save_version,
            "python_node_list": [
                {
                    "id": non_declaring_python_node.id,
                    "graph": graph.id,
                    "node_name": "clearable",
                    "python_code": {
                        "code": "def main(**kwargs):\n    return 1\n",
                        "entrypoint": "main",
                        "libraries": [],
                        "global_kwargs": {},
                        "secret_ids": [],
                    },
                }
            ],
        }

        response = admin_client.post(
            f"/api/graphs/{graph.id}/save/", payload, format="json"
        )

        assert response.status_code == 200, response.json()
        non_declaring_python_node.python_code.refresh_from_db()
        assert list(non_declaring_python_node.python_code.secrets.all()) == []
