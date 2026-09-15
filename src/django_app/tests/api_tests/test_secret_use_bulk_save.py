"""Bulk flow save gates a changed secret declaration behind secrets:USE, per node."""

import pytest
from rest_framework.test import APIClient

from tables.models import PythonCode
from tables.models.graph_models import Graph, PythonNode
from tables.models.rbac_models import (
    Organization,
    OrganizationUser,
    Role,
    RolePermission,
)
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.secrets import secret_service

NEUTRAL_CODE = "def main(**kwargs):\n    return 1\n"


def _payload(graph, node, *, secret_ids):
    """Build a bulk-save payload for one existing PythonNode, omitting secret_ids when None."""
    python_code = {
        "code": node.python_code.code,
        "entrypoint": node.python_code.entrypoint,
        "libraries": [],
        "global_kwargs": {},
    }
    if secret_ids is not None:
        python_code["secret_ids"] = secret_ids
    return {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": node.node_name,
                "python_code": python_code,
            }
        ],
    }


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org BulkUse")


def _client_with(*, org, django_user_model, email, secrets_bitmask):
    """An APIClient for a user whose custom role holds `secrets_bitmask` on secrets and CREATE|READ|UPDATE on flows."""
    role = Role.objects.create(name=f"role-{email}", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.SECRETS.value, permissions=secrets_bitmask
    )
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.FLOWS.value,
        permissions=int(Permission.CREATE | Permission.READ | Permission.UPDATE),
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def no_use_client(db, django_user_model, org):
    return _client_with(
        org=org,
        django_user_model=django_user_model,
        email="bulkuse_nouse@example.com",
        secrets_bitmask=int(Permission.READ),
    )


@pytest.fixture
def use_client(db, django_user_model, org):
    return _client_with(
        org=org,
        django_user_model=django_user_model,
        email="bulkuse_use@example.com",
        secrets_bitmask=int(Permission.READ | Permission.USE),
    )


@pytest.fixture
def secret(org):
    return secret_service.create(text="sk-bulkuse", org=org, name="BULKUSE_KEY")


@pytest.fixture
def other_secret(org):
    return secret_service.create(text="sk-bulkuse-2", org=org, name="BULKUSE_OTHER_KEY")


@pytest.fixture
def graph(org):
    return Graph.objects.create(name="BulkUse flow", org=org)


@pytest.fixture
def python_node(graph, secret):
    python_code = PythonCode.objects.create(code=NEUTRAL_CODE, entrypoint="main")
    python_code.secrets.set([secret])
    return PythonNode.objects.create(
        graph=graph, node_name="declarer", python_code=python_code
    )


@pytest.fixture
def plain_node(graph):
    python_code = PythonCode.objects.create(code=NEUTRAL_CODE, entrypoint="main")
    return PythonNode.objects.create(
        graph=graph, node_name="plain", python_code=python_code
    )


@pytest.mark.django_db
class TestBulkSaveUnderTheGuard:
    def test_resending_an_unchanged_declaration_is_accepted(
        self, no_use_client, graph, python_node, secret
    ):
        response = no_use_client.post(
            f"/api/graphs/{graph.id}/save/",
            _payload(graph, python_node, secret_ids=[secret.id]),
            format="json",
        )
        assert response.status_code == 200, response.json()

    def test_omitting_the_declaration_is_accepted_and_preserves_it(
        self, no_use_client, graph, python_node, secret
    ):
        response = no_use_client.post(
            f"/api/graphs/{graph.id}/save/",
            _payload(graph, python_node, secret_ids=None),
            format="json",
        )

        assert response.status_code == 200, response.json()
        python_node.python_code.refresh_from_db()
        assert list(python_node.python_code.secrets.values_list("name", flat=True)) == [
            "BULKUSE_KEY"
        ]

    def test_changing_one_node_is_rejected_and_attributed_to_that_node(
        self, no_use_client, graph, python_node, other_secret
    ):
        response = no_use_client.post(
            f"/api/graphs/{graph.id}/save/",
            _payload(graph, python_node, secret_ids=[other_secret.id]),
            format="json",
        )

        assert response.status_code == 400
        errors = response.json()["errors"]["python_node_list"]
        assert errors[0]["index"] == 0
        assert "secret_ids" in errors[0]["errors"]["python_code"]

    def test_a_rejected_save_writes_nothing(
        self, no_use_client, graph, python_node, other_secret
    ):
        before = graph.save_version

        no_use_client.post(
            f"/api/graphs/{graph.id}/save/",
            _payload(graph, python_node, secret_ids=[other_secret.id]),
            format="json",
        )

        graph.refresh_from_db()
        python_node.python_code.refresh_from_db()
        assert graph.save_version == before
        assert list(python_node.python_code.secrets.values_list("name", flat=True)) == [
            "BULKUSE_KEY"
        ]

    def test_editing_an_unrelated_node_is_accepted(
        self, no_use_client, graph, python_node, plain_node, secret
    ):
        """The regression test for the whole design — if this fails, the delta rule is broken."""
        payload = _payload(graph, python_node, secret_ids=[secret.id])
        payload["python_node_list"].append(
            {
                "id": plain_node.id,
                "graph": graph.id,
                "node_name": "plain",
                "python_code": {
                    "code": "def main(**kwargs):\n    return 2\n",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                },
            }
        )

        response = no_use_client.post(
            f"/api/graphs/{graph.id}/save/", payload, format="json"
        )

        assert response.status_code == 200, response.json()

    def test_the_same_change_with_use_is_accepted(
        self, use_client, graph, python_node, other_secret
    ):
        response = use_client.post(
            f"/api/graphs/{graph.id}/save/",
            _payload(graph, python_node, secret_ids=[other_secret.id]),
            format="json",
        )
        assert response.status_code == 200, response.json()

    # Intentional precedence: `PythonCodeSerializer.validate()` calls
    # `super().validate()` as its first line, which is where the guard runs, and
    # only afterwards runs its own allow-list check later in the same method body.
    # So when both would independently reject a payload, the guard raises first and
    # the allow-list code never executes. This is deliberate — authorization is
    # decided before content validation is even attempted — and does not depend on
    # `SecretReferenceGuardMixin`'s position in the base list, since
    # `PythonCodeSerializer` defines its own `validate()` as the actual entry point.
    def test_permission_error_wins_when_both_checks_would_fail(
        self, no_use_client, graph, python_node, other_secret
    ):
        payload = _payload(graph, python_node, secret_ids=[other_secret.id])
        payload["python_node_list"][0]["python_code"]["code"] = (
            'def main(**kwargs):\n    return get_secret("SOMETHING_UNDECLARED")\n'
        )

        response = no_use_client.post(
            f"/api/graphs/{graph.id}/save/", payload, format="json"
        )

        assert response.status_code == 400
        message = response.json()["errors"]["python_node_list"][0]["errors"][
            "python_code"
        ]["secret_ids"][0]
        assert "Use" in message and "permission" in message
        assert "get_secret" not in message
