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
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole, Permission
from tables.services.secrets import secret_service
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants

DECLARING_CODE = 'def main(**kwargs):\n    return get_secret("DECL_KEY")\n'
TYPO_CODE = 'def main(**kwargs):\n    return get_secret("DECL_KYE")\n'


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
def member_client(db, django_user_model, org):
    role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(
        email="decl_member@example.com", password="StrongPass123!"
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
def unlinked_secret(org):
    """A secret of the org that no PythonCode links to: its name is not readable on any node."""
    return secret_service.create(text="sk-unlinked", org=org, name="UNLINKED_KEY")


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
    def test_copy_python_code_keeps_declared_secrets(self, django_user_model, org, secret):
        """Copy stays inside one org, so the ids remain valid and the copy must be
        runnable — dropping the declaration would silently break the duplicate."""
        from tables.services.copy_services.helpers import copy_python_code
        from tables.services.secrets.secret_use_service import SecretActor

        user = django_user_model.objects.create_user(
            email="decl_copier@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(
            user=user,
            org=org,
            role=Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True),
        )
        original = PythonCode.objects.create(code=DECLARING_CODE, entrypoint="main")
        original.secrets.set([secret])

        duplicate = copy_python_code(original, actor=SecretActor(user=user, org_id=org.id))

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
                    "code": TYPO_CODE,
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
        assert "Available in this organization: DECL_KEY." in message

    def test_a_member_without_secrets_read_is_not_shown_the_org_secret_names(
        self, member_client, graph, secret
    ):
        """A Member gets 403 on the secrets list, so the error must not list them either."""
        resp = member_client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "member_typo",
                "python_code": {
                    "code": TYPO_CODE,
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
        assert "DECL_KEY" not in message
        assert "Available in this organization" not in message
        assert "Select them under Secrets, or remove the calls." in message

    @pytest.mark.parametrize(
        ("secrets_permissions", "lists_names"),
        [
            (int(Permission.READ), True),
            (int(Permission.USE), False),
            (0, False),
        ],
    )
    def test_the_list_follows_secrets_read_not_the_role(
        self, django_user_model, org, graph, secret, secrets_permissions, lists_names
    ):
        client = client_with_grants(
            org=org,
            django_user_model=django_user_model,
            email=f"decl_custom_{secrets_permissions}@example.com",
            resource_permissions={
                "flows": FULL_CRUD,
                "secrets": secrets_permissions,
            },
        )

        resp = client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "custom_typo",
                "python_code": {
                    "code": TYPO_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                },
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        assert ("DECL_KEY" in str(resp.data)) is lists_names

    @pytest.mark.parametrize("key_type", ["user", "system"])
    def test_an_api_key_is_not_shown_the_org_secret_names(
        self, issue_api_key, admin_client, org, graph, secret, key_type
    ):
        """The secrets list endpoint refuses personal and system API keys, even when the
        key's owner holds secrets READ or the key acts as a superadmin, so the error must
        not list the names to such a key either."""
        if key_type == "user":
            admin = OrganizationUser.objects.get(
                org=org, user__email="decl_admin@example.com"
            ).user
            raw_key, _ = issue_api_key(user=admin, org=org)
        else:
            raw_key, _ = issue_api_key(user=None)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(org.id))

        resp = client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "api_key_typo",
                "python_code": {
                    "code": TYPO_CODE,
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
        assert "DECL_KEY" not in message
        assert "Available in this organization" not in message

    def test_a_member_cannot_read_an_unlinked_secret_name_through_the_selection(
        self, member_client, graph, unlinked_secret
    ):
        """A Member holds neither secrets READ nor USE. Selecting a secret by id must be
        refused before the error names it, or the Member could walk the ids and read
        every secret name of the org one at a time."""
        resp = member_client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "member_probe",
                "python_code": {
                    "code": TYPO_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [unlinked_secret.pk],
                },
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        assert "UNLINKED_KEY" not in str(resp.data)
        assert resp.json()["message"].startswith(
            'python_code: secret_ids: Changing the secrets referenced here requires the "Use"'
        )
        assert not PythonNode.objects.filter(node_name="member_probe").exists()

    def test_a_member_cannot_read_an_unlinked_secret_name_when_editing_a_node(
        self, member_client, graph, secret, unlinked_secret
    ):
        """The same probe on an update: what the node already links to may be named, the
        newly selected secret may not."""
        node = PythonNode.objects.create(
            graph=graph,
            node_name="member_probe_update",
            python_code=PythonCode.objects.create(code=DECLARING_CODE, entrypoint="main"),
        )
        node.python_code.secrets.set([secret])

        resp = member_client.patch(
            f"/api/pythonnodes/{node.pk}/",
            {
                "python_code": {
                    "code": TYPO_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [secret.pk, unlinked_secret.pk],
                }
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        assert "UNLINKED_KEY" not in str(resp.data)
        assert list(node.python_code.secrets.values_list("name", flat=True)) == ["DECL_KEY"]

    def test_resending_what_the_node_links_to_still_names_it(
        self, member_client, graph, secret
    ):
        """An unchanged selection needs no Use, and its names are already readable on the
        node, so the error keeps naming them."""
        node = PythonNode.objects.create(
            graph=graph,
            node_name="member_resend",
            python_code=PythonCode.objects.create(code=DECLARING_CODE, entrypoint="main"),
        )
        node.python_code.secrets.set([secret])

        resp = member_client.patch(
            f"/api/pythonnodes/{node.pk}/",
            {
                "python_code": {
                    "code": TYPO_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [secret.pk],
                }
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        message = resp.json()["message"]
        assert 'get_secret("DECL_KYE")' in message
        assert "Selected: DECL_KEY." in message

    @pytest.mark.parametrize(
        ("secrets_permissions", "use_refused"),
        [
            (0, True),
            (int(Permission.READ), True),
            (int(Permission.USE), False),
        ],
    )
    def test_selecting_a_secret_follows_secrets_use(
        self,
        django_user_model,
        org,
        graph,
        unlinked_secret,
        secrets_permissions,
        use_refused,
    ):
        """Only a caller allowed to select the secret gets the undeclared-secret error that
        names it: once saved, it could read the name back on the node anyway."""
        client = client_with_grants(
            org=org,
            django_user_model=django_user_model,
            email=f"decl_select_{secrets_permissions}@example.com",
            resource_permissions={"flows": FULL_CRUD, "secrets": secrets_permissions},
        )

        resp = client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "custom_probe",
                "python_code": {
                    "code": TYPO_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [unlinked_secret.pk],
                },
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        message = resp.json()["message"]
        assert ('requires the "Use" permission on Secrets' in message) is use_refused
        assert ("Selected: UNLINKED_KEY." in message) is not use_refused

    def test_a_user_api_key_without_secrets_use_cannot_read_an_unlinked_secret_name(
        self, issue_api_key, django_user_model, org, graph, unlinked_secret
    ):
        """A USER key acts with its owner's permissions: a Member owner lacks secrets USE,
        so the selection is refused before the error could name the secret."""
        role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
        owner = django_user_model.objects.create_user(
            email="decl_key_member@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=owner, org=org, role=role)
        raw_key, _ = issue_api_key(user=owner, org=org)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(org.id))

        resp = client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "user_key_probe",
                "python_code": {
                    "code": TYPO_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [unlinked_secret.pk],
                },
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        assert "UNLINKED_KEY" not in str(resp.data)
        assert 'requires the "Use" permission on Secrets' in resp.json()["message"]
        assert not PythonNode.objects.filter(node_name="user_key_probe").exists()

    def test_a_system_api_key_is_named_the_secret_it_may_select(
        self, issue_api_key, org, graph, unlinked_secret
    ):
        """A SYSTEM key acts as a superadmin, so it holds secrets USE and may make the
        selection. Naming the secret reveals nothing new: the key could save the selection
        and read the name back from the node's `secrets` field. Only the org-wide
        "Available" list stays hidden, as the secrets list endpoint refuses the key."""
        raw_key, _ = issue_api_key(user=None)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(org.id))

        resp = client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.pk,
                "node_name": "system_key_probe",
                "python_code": {
                    "code": TYPO_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [unlinked_secret.pk],
                },
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        message = resp.json()["message"]
        assert "Selected: UNLINKED_KEY." in message
        assert "Available in this organization" not in message
        assert "permission" not in message
        assert not PythonNode.objects.filter(node_name="system_key_probe").exists()

    def test_a_tool_cannot_be_used_to_read_an_unlinked_secret_name(
        self, member_client, unlinked_secret
    ):
        """A tool nests the same PythonCode, so the same probe through it is refused too."""
        resp = member_client.post(
            "/api/python-code-tool/",
            {
                "name": "member_probe_tool",
                "description": "probe",
                "variables": [],
                "python_code": {
                    "code": TYPO_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [unlinked_secret.pk],
                },
            },
            format="json",
        )

        assert resp.status_code == 400, resp.content
        assert "UNLINKED_KEY" not in str(resp.data)
        assert resp.json()["message"].startswith(
            'python_code: secret_ids: Changing the secrets referenced here requires the "Use"'
        )

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
    """One validate() covers all five sites only because they all nest the same
    serializer. If a site ever swaps in its own, validation silently stops applying
    there — so the claim is asserted rather than trusted.
    """
    from tables.serializers.model_serializers.node_serializers.basic_node_serializers import (
        PythonNodeSerializer,
    )
    from tables.serializers.model_serializers.node_serializers.flow_control_serializers import (
        ClassificationDecisionTableNodeSerializer,
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
        ClassificationDecisionTableNodeSerializer().fields["pre_python_code"],
        ClassificationDecisionTableNodeSerializer().fields["post_python_code"],
        PythonCodeToolSerializer().fields["python_code"],
    ]

    assert len(nested) == 5
    for field in nested:
        assert isinstance(field, PythonCodeSerializer)
