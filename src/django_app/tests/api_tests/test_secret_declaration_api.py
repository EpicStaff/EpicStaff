"""Declaring secrets on a node's python_code, over the API and with no frontend.

An explicit APIClient is built here rather than using the shared auth_client
fixture: tests/settings.py clears DEFAULT_AUTHENTICATION_CLASSES, which makes that
fixture return 403 for everything. Pattern follows
tests/api_tests/test_secret_selection_cross_org.py.
"""

import pytest
from rest_framework.test import APIClient

from tables.models import PythonCode
from tables.models.graph_models import Graph, PythonNode
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_service

DECLARING_CODE = 'def main(**kwargs):\n    return get_secret("DECL_KEY")\n'


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org SecretDecl")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org SecretDecl Other")


@pytest.fixture
def admin_client(db, django_user_model, org):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="decl_admin@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def secret(org):
    return secret_service.create(text="sk-decl", org=org, name="DECL_KEY")


@pytest.fixture
def graph(org):
    return Graph.objects.create(name="Decl flow", org=org)


@pytest.mark.django_db
class TestDeclaringViaTheApi:
    def test_python_node_create_stores_the_declaration(
        self, admin_client, graph, secret
    ):
        """The whole point: declaring works over the API with no frontend."""
        resp = admin_client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "charge_card",
                "python_code": {
                    "code": DECLARING_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [secret.pk],
                },
            },
            format="json",
        )

        assert resp.status_code == 201, resp.content
        node = PythonNode.objects.get(node_name="charge_card")
        assert list(node.python_code.secrets.values_list("name", flat=True)) == [
            "DECL_KEY"
        ]

    def test_declaration_is_write_only(self, admin_client, graph, secret):
        """secret_ids is a write field; the response must not echo it back, because
        read shape is the frontend's contract and it reads the relation itself."""
        resp = admin_client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "write_only",
                "python_code": {
                    "code": "def main(**kwargs):\n    return 1\n",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [secret.pk],
                },
            },
            format="json",
        )

        assert resp.status_code == 201, resp.content
        assert "secret_ids" not in resp.data["python_code"]

    def test_no_declaration_is_allowed(self, admin_client, graph):
        """Omitting secret_ids must not be an error — most nodes use no secrets."""
        resp = admin_client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "no_secrets",
                "python_code": {
                    "code": "def main(**kwargs):\n    return 1\n",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                },
            },
            format="json",
        )

        assert resp.status_code == 201, resp.content
        node = PythonNode.objects.get(node_name="no_secrets")
        assert node.python_code.secrets.count() == 0

    def test_another_orgs_secret_is_rejected_as_a_bad_pk(
        self, admin_client, graph, other_org
    ):
        """Existence in another org must not be revealed: the error must be the
        standard invalid-pk 400, identical to an id that does not exist at all."""
        foreign = secret_service.create(
            text="sk-foreign", org=other_org, name="FOREIGN_KEY"
        )

        resp = admin_client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "foreign",
                "python_code": {
                    "code": "def main(**kwargs):\n    return 1\n",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [foreign.pk],
                },
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        assert "does not exist" in str(resp.data)
        assert not PythonNode.objects.filter(node_name="foreign").exists()

    def test_update_replaces_the_declaration(self, admin_client, graph, org, secret):
        other_secret = secret_service.create(
            text="sk-decl-2", org=org, name="DECL_KEY_2"
        )
        node = PythonNode.objects.create(
            graph=graph,
            node_name="replace_me",
            python_code=PythonCode.objects.create(
                code="def main(**kwargs):\n    return 1\n"
            ),
        )
        node.python_code.secrets.set([secret])

        resp = admin_client.patch(
            f"/api/pythonnodes/{node.pk}/",
            {
                "python_code": {
                    "code": "def main(**kwargs):\n    return 1\n",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [other_secret.pk],
                }
            },
            format="json",
        )

        assert resp.status_code == 200, resp.content
        node.python_code.refresh_from_db()
        assert list(node.python_code.secrets.values_list("name", flat=True)) == [
            "DECL_KEY_2"
        ]


@pytest.mark.django_db
class TestPythonCodeToolDeclaration:
    def test_tool_create_stores_the_declaration(self, admin_client, secret):
        resp = admin_client.post(
            "/api/python-code-tool/",
            {
                "name": "decl tool",
                "description": "declares a secret",
                "variables": [],
                "python_code": {
                    "code": DECLARING_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [secret.pk],
                },
            },
            format="json",
        )

        assert resp.status_code == 201, resp.content
        from tables.models import PythonCodeTool

        tool = PythonCodeTool.objects.get(name="decl tool")
        assert list(tool.python_code.secrets.values_list("name", flat=True)) == [
            "DECL_KEY"
        ]


@pytest.mark.django_db
class TestCopyCarriesTheDeclaration:
    def test_copy_python_code_keeps_declared_secrets(self, org, secret):
        """Copy stays inside one org, so the ids remain valid and the copy must be
        runnable — dropping the declaration would silently break the duplicate."""
        from tables.services.copy_services.helpers import copy_python_code

        original = PythonCode.objects.create(code=DECLARING_CODE, entrypoint="main")
        original.secrets.set([secret])

        duplicate = copy_python_code(original)

        assert duplicate.pk != original.pk
        assert list(duplicate.secrets.values_list("name", flat=True)) == ["DECL_KEY"]


@pytest.mark.django_db
class TestSaveTimeValidation:
    def test_undeclared_secret_is_rejected_on_create(self, admin_client, graph, secret):
        resp = admin_client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "undeclared",
                "python_code": {
                    "code": DECLARING_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                },
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        assert "DECL_KEY" in str(resp.data)
        assert not PythonNode.objects.filter(node_name="undeclared").exists()

    def test_the_error_lists_what_is_available(self, admin_client, graph, secret):
        """Nothing teaches the get_secret syntax, so the failure has to. Listing the
        org's secret names turns a wrong guess into a corrected one."""
        resp = admin_client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "typo",
                "python_code": {
                    "code": 'def main(**kwargs):\n    return get_secret("DECL_KYE")\n',
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                },
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        message = str(resp.data)
        assert "DECL_KYE" in message
        assert "DECL_KEY" in message

    def test_every_undeclared_name_is_reported_not_just_the_first(
        self, admin_client, graph
    ):
        resp = admin_client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "two_missing",
                "python_code": {
                    "code": (
                        "def main(**kwargs):\n"
                        '    return get_secret("ALPHA_KEY"), get_secret("BETA_KEY")\n'
                    ),
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                },
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        message = str(resp.data)
        assert "ALPHA_KEY" in message
        assert "BETA_KEY" in message

    def test_declared_but_unused_is_allowed(self, admin_client, graph, secret):
        """A secret may be selected before the code that reads it exists."""
        resp = admin_client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "unused_decl",
                "python_code": {
                    "code": "def main(**kwargs):\n    return 1\n",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [secret.pk],
                },
            },
            format="json",
        )

        assert resp.status_code == 201, resp.content

    def test_a_name_only_in_a_comment_does_not_block_the_save(
        self, admin_client, graph
    ):
        """The parser guarantees this, asserted here because it is now a *gate*: a
        false positive would block a legitimate save."""
        resp = admin_client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "commented",
                "python_code": {
                    "code": (
                        "def main(**kwargs):\n"
                        '    # get_secret("DECL_KEY") one day\n'
                        "    return 1\n"
                    ),
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                },
            },
            format="json",
        )

        assert resp.status_code == 201, resp.content

    def test_patching_code_alone_validates_against_stored_declarations(
        self, admin_client, graph, secret
    ):
        """A PATCH carries only what changed, so validate() must read the
        declaration off the instance or editing code never gets checked."""
        node = PythonNode.objects.create(
            graph=graph,
            node_name="patch_code",
            python_code=PythonCode.objects.create(
                code="def main(**kwargs):\n    return 1\n"
            ),
        )

        resp = admin_client.patch(
            f"/api/pythonnodes/{node.pk}/",
            {
                "python_code": {
                    "code": DECLARING_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                }
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        assert "DECL_KEY" in str(resp.data)

    def test_patching_the_declaration_away_is_rejected(
        self, admin_client, graph, secret
    ):
        """The dangerous direction, and the one that would have been missed:
        removing a secret the stored code still reads must not silently succeed. It
        would leave the node in exactly the state validation exists to prevent."""
        node = PythonNode.objects.create(
            graph=graph,
            node_name="patch_decl",
            python_code=PythonCode.objects.create(
                code=DECLARING_CODE, entrypoint="main"
            ),
        )
        node.python_code.secrets.set([secret])

        resp = admin_client.patch(
            f"/api/pythonnodes/{node.pk}/",
            {
                "python_code": {
                    "code": DECLARING_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [],
                }
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        node.python_code.refresh_from_db()
        assert node.python_code.secrets.count() == 1


@pytest.mark.django_db
def test_every_python_code_nesting_site_shares_the_validating_serializer():
    """One validate() covers all six sites only because they all nest the same
    serializer. If a site ever swaps in its own, validation silently stops applying
    there — so the claim is asserted rather than trusted.
    """
    from tables.serializers.model_serializers.node_serializers.basic_node_serializers import (
        PythonNodeSerializer,
    )
    from tables.serializers.model_serializers.node_serializers.flow_control_serializers import (
        ClassificationDecisionTableNodeSerializer,
        ConditionalEdgeSerializer,
    )
    from tables.serializers.model_serializers.node_serializers.trigger_serializers import (
        WebhookTriggerNodeSerializer,
    )
    from tables.serializers.model_serializers.python_serializers import (
        PythonCodeSerializer,
        PythonCodeToolSerializer,
    )

    nested = [
        PythonNodeSerializer().fields["python_code"],
        WebhookTriggerNodeSerializer().fields["python_code"],
        ConditionalEdgeSerializer().fields["python_code"],
        ClassificationDecisionTableNodeSerializer().fields["pre_python_code"],
        ClassificationDecisionTableNodeSerializer().fields["post_python_code"],
        PythonCodeToolSerializer().fields["python_code"],
    ]

    assert len(nested) == 6
    for field in nested:
        assert isinstance(field, PythonCodeSerializer)
