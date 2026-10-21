"""A principal pinned to one organization, through rbac and the tables code it reaches.

The principal here is a fake that implements `PinnedOrgPrincipal` and nothing else:
rbac and tables must work with any implementation of the protocol, and must never
learn which app supplies the real one.
"""

from types import SimpleNamespace
from uuid import uuid4

import fakeredis
import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth.models import AnonymousUser
from django.test import override_settings
from django.utils import timezone
from rbac.access.asserts import assert_row_org_permission
from rbac.access.effective import EffectivePermissions
from rbac.access.gates import (
    DenyApiKeyAuth,
    DenyPersonalAndSystemApiKeys,
    DenyPluginCredential,
    RestrictApiKeyToUserKeyReads,
)
from rbac.access.org_context import OrgContextService
from rbac.access.principals import (
    PinnedOrgPrincipal,
    acting_person,
    is_pinned_org_principal,
    is_plugin_credential,
)
from rbac.access.resolver import PermissionResolver
from rbac.exceptions import (
    OrganizationNotFoundError,
    OrgMembershipRequiredError,
)
from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models.enums import Permission, ResourceType
from rest_framework.exceptions import PermissionDenied
from rest_framework.settings import api_settings
from rest_framework.test import APIClient, APIRequestFactory
from src.shared.models import GraphData, SessionData
from tables.exceptions import GraphNotFoundError
from tables.graph_collab.utils import build_editor_info
from tables.import_export.export_tabular_projections.session import (
    SessionTabularProjection,
)
from tables.import_export.serializers.session import SessionPrincipalExportSerializer
from tables.models import McpTool, StorageFile
from tables.models.llm_models import LLMModel
from tables.models.graph_models import Graph, GraphOrganizationUser, GraphSessionMessage
from tables.models.session_models import Session, SessionPrincipal
from tables.serializers.model_serializers.session_serializers import (
    SessionPrincipalSerializer,
)
from tables.services.graph_message_store import GraphMessageStore
from tables.services.persistent_variables_service import PersistentVariablesService
from tables.serializers.model_serializers.llm_serializers import LLMConfigSerializer, LLMModelSerializer
from tables.services.secrets import secret_service
from tables.services.secrets.reference_guard import secret_destination_guard, secret_reference_guard
from tables.services.session_access import get_runnable_graph
from tables.services.session_manager_service import SessionManagerService
from tables.services.storage_service.db_sync import StorageFileSync
from tables.services.trigger_spec import TriggerSpec
from tables.signals import rows_bulk_created
from tables.throttles import NotifyEmailThrottle
from tables.views.storage_bin_purge_access import StorageBinPurgeAccess
from tables.views.storage_views import StorageAPIView

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

PLUGIN_REFUSED = "Plugin service accounts cannot use this endpoint."

DECLARED = {
    ResourceType.FLOWS: Permission.READ | Permission.CREATE | Permission.UPDATE | Permission.USE,
    ResourceType.SECRETS: Permission.READ | Permission.CREATE | Permission.USE,
    ResourceType.TOOLS: Permission.READ,
    ResourceType.FILES: Permission.READ | Permission.CREATE | Permission.UPDATE | Permission.DELETE,
    # Neither is declarable by a real plugin; granted here so that a refusal on the
    # person-only surfaces below can only come from DenyPluginCredential.
    ResourceType.AUDIT: Permission.READ,
    ResourceType.AGENTS: Permission.READ,
}


class FakePinnedPrincipal:
    """Implements `PinnedOrgPrincipal`; deliberately no id, pk or email."""

    is_authenticated = True
    is_anonymous = False
    is_superadmin = False
    is_plugin_credential = True

    def __init__(self, org_id: int, by_resource: dict | None = None, person=None, references_secrets=True):
        self.pinned_org_id = org_id
        self.plugin_identifier = "fakeplugin"
        self.display_name = "Fake (plugin)"
        self.person = person
        self.rate_limit_key = f"fake-plugin-account:{org_id}"
        self._by_resource = {str(key): int(bits) for key, bits in (by_resource or DECLARED).items()}
        self._references_secrets = references_secrets
        self.secret_reference_questions: list[frozenset[int]] = []

    def resolve_effective_permissions(self, org_id: int) -> EffectivePermissions:
        return EffectivePermissions(is_superadmin=False, role=None, by_resource=self._by_resource)

    def may_reference_secrets(self, secret_ids: frozenset[int]) -> bool:
        self.secret_reference_questions.append(secret_ids)
        return self._references_secrets


class FakePluginKey:
    is_plugin_credential = True


@pytest.fixture
def principal(acme):
    return FakePinnedPrincipal(acme.id)


@pytest.fixture
def principal_for_member(acme, member_only):
    return FakePinnedPrincipal(acme.id, person=member_only)


@pytest.fixture
def plugin_client():
    """An APIClient authenticated as the given principal with a plugin key."""

    def _make(principal, org_id: int | None = None):
        client = APIClient()
        client.force_authenticate(user=principal, token=FakePluginKey())
        if org_id is not None:
            client.credentials(HTTP_X_ORGANIZATION_ID=str(org_id))
        return client

    return _make


def _request(user, auth=None, method="GET", org_header=None):
    headers = {"X-Organization-Id": str(org_header)} if org_header is not None else {}
    return SimpleNamespace(user=user, auth=auth, method=method, headers=headers)


def _stub_publish(monkeypatch) -> SessionManagerService:
    session_manager = SessionManagerService()
    monkeypatch.setattr(
        session_manager,
        "create_session_data",
        lambda session, **kwargs: SessionData(
            id=1, org_id=1, graph=GraphData(name="stub", entrypoint="__end__", end_node=None)
        ),
    )
    monkeypatch.setattr(session_manager.redis_service, "publish_session_data", lambda **kwargs: 2)
    return session_manager


# ---- The protocol and its helpers ----


def test_fake_principal_implements_the_protocol(principal):
    assert isinstance(principal, PinnedOrgPrincipal)
    assert is_pinned_org_principal(principal) is True


def test_users_and_other_principals_are_not_pinned(member_only):
    for user in (member_only, SystemServicePrincipal(), AnonymousUser(), None):
        assert is_pinned_org_principal(user) is False


def test_acting_person(member_only, principal, principal_for_member):
    assert acting_person(member_only) == member_only
    assert acting_person(principal_for_member) == member_only
    assert acting_person(principal) is None
    assert acting_person(SystemServicePrincipal()) is None
    assert acting_person(AnonymousUser()) is None


def test_is_plugin_credential(member_only, principal, issue_api_key):
    _, user_key = issue_api_key(user=member_only)

    assert is_plugin_credential(_request(principal, FakePluginKey())) is True
    assert is_plugin_credential(_request(principal)) is True
    assert is_plugin_credential(_request(member_only, FakePluginKey())) is True
    assert is_plugin_credential(_request(member_only)) is False
    assert is_plugin_credential(_request(member_only, user_key)) is False
    # Only a literal True counts.
    assert is_plugin_credential(_request(SimpleNamespace(is_plugin_credential=1))) is False


# ---- PermissionResolver ----


def test_resolver_returns_declared_bits_in_the_pinned_org(principal, acme):
    effective = PermissionResolver().resolve(user=principal, org_id=acme.id)

    assert effective.is_superadmin is False
    assert effective.can(ResourceType.FLOWS, Permission.CREATE)
    assert effective.can(ResourceType.SECRETS, Permission.USE)
    assert not effective.can(ResourceType.FLOWS, Permission.DELETE)
    assert not effective.can(ResourceType.KNOWLEDGE_SOURCES, Permission.READ)


def test_resolver_treats_another_org_as_not_a_member(principal, beta):
    with pytest.raises(OrgMembershipRequiredError):
        PermissionResolver().resolve(user=principal, org_id=beta.id)


def test_row_in_another_org_answers_the_views_own_not_found(principal, beta):
    with pytest.raises(GraphNotFoundError):
        assert_row_org_permission(
            principal,
            beta.id,
            ResourceType.FLOWS,
            Permission.READ,
            not_found=GraphNotFoundError(),
        )


def test_row_in_the_pinned_org_without_the_declared_action_is_403(principal, acme):
    with pytest.raises(PermissionDenied):
        assert_row_org_permission(
            principal,
            acme.id,
            ResourceType.FLOWS,
            Permission.DELETE,
            not_found=GraphNotFoundError(),
        )


def test_running_another_orgs_flow_is_not_found(principal, beta):
    other_graph = Graph.objects.create(name="beta flow", org=beta)

    with pytest.raises(GraphNotFoundError):
        get_runnable_graph(principal, graph_id=other_graph.id)


# ---- OrgContextService ----


def test_org_context_without_header_is_the_pinned_org(principal, acme):
    assert OrgContextService().resolve(request=_request(principal), view_kwargs={}) == acme.id


def test_org_context_with_the_pinned_orgs_header(principal, acme):
    request = _request(principal, org_header=acme.id)
    assert OrgContextService().resolve(request=request, view_kwargs={}) == acme.id


def test_org_context_with_another_orgs_header_is_not_found(principal, beta):
    with pytest.raises(OrganizationNotFoundError):
        OrgContextService().resolve(request=_request(principal, org_header=beta.id))


def test_org_context_with_the_pinned_orgs_url_kwarg(principal, acme):
    resolved = OrgContextService().resolve(
        request=_request(principal), view_kwargs={"org_id": str(acme.id)}
    )

    assert resolved == acme.id


def test_org_context_with_another_orgs_url_kwarg_is_not_found(principal, acme, beta):
    request = _request(principal, org_header=acme.id)
    with pytest.raises(OrganizationNotFoundError):
        OrgContextService().resolve(request=request, view_kwargs={"org_id": beta.id})


def test_org_context_for_an_inactive_pinned_org_is_refused(principal, acme):
    acme.is_active = False
    acme.save(update_fields=["is_active"])

    with pytest.raises(OrgMembershipRequiredError):
        OrgContextService().resolve(request=_request(principal))


def test_org_scoped_list_without_header_lists_the_pinned_org_only(
    plugin_client, principal, acme, beta
):
    Graph.objects.create(name="acme flow", org=acme)
    Graph.objects.create(name="beta flow", org=beta)

    response = plugin_client(principal).get("/api/graphs/")

    assert response.status_code == 200, response.content
    assert [graph["name"] for graph in response.json()["results"]] == ["acme flow"]


def test_another_orgs_header_answers_404_organization_not_found(plugin_client, principal, beta):
    response = plugin_client(principal, org_id=beta.id).get("/api/graphs/")

    assert response.status_code == 404, response.content
    assert response.json()["code"] == "organization_not_found"


def test_inactive_pinned_org_answers_403(plugin_client, principal, acme):
    acme.is_active = False
    acme.save(update_fields=["is_active"])

    response = plugin_client(principal).get("/api/graphs/")

    assert response.status_code == 403, response.content
    assert response.json()["code"] == "org_membership_required"


# ---- Gates ----


def test_deny_api_key_auth_refuses_a_plugin_credential(principal, member_only, issue_api_key):
    gate = DenyApiKeyAuth()
    assert gate.has_permission(_request(principal, FakePluginKey()), view=None) is False
    assert gate.message == PLUGIN_REFUSED

    _, user_key = issue_api_key(user=member_only)
    _, system_key = issue_api_key(user=None)
    assert DenyApiKeyAuth().has_permission(_request(member_only, user_key), view=None) is False
    assert DenyApiKeyAuth().has_permission(_request(member_only, system_key), view=None) is False
    assert DenyApiKeyAuth().has_permission(_request(member_only), view=None) is True


def test_restrict_api_key_to_user_key_reads_refuses_a_plugin_credential(principal, member_only):
    gate = RestrictApiKeyToUserKeyReads()
    assert gate.has_permission(_request(principal, FakePluginKey()), view=None) is False
    assert gate.message == RestrictApiKeyToUserKeyReads.plugin_credential_message
    assert RestrictApiKeyToUserKeyReads().has_permission(_request(member_only), view=None) is True


def test_deny_plugin_credential_refuses_only_plugin_credentials(
    principal, member_only, issue_api_key
):
    _, user_key = issue_api_key(user=member_only)
    _, system_key = issue_api_key(user=None)
    gate = DenyPluginCredential()

    assert gate.has_permission(_request(principal, FakePluginKey()), view=None) is False
    assert gate.has_permission(_request(member_only), view=None) is True
    assert gate.has_permission(_request(member_only, user_key), view=None) is True
    assert gate.has_permission(_request(SystemServicePrincipal(), system_key), view=None) is True


def test_deny_personal_and_system_api_keys_passes_a_plugin_credential(
    principal, member_only, issue_api_key
):
    _, user_key = issue_api_key(user=member_only)
    _, system_key = issue_api_key(user=None)
    gate = DenyPersonalAndSystemApiKeys()

    assert gate.has_permission(_request(principal, FakePluginKey()), view=None) is True
    assert gate.has_permission(_request(member_only), view=None) is True
    assert gate.has_permission(_request(member_only, user_key), view=None) is False
    assert gate.has_permission(_request(SystemServicePrincipal(), system_key), view=None) is False


# ---- Where each gate is placed ----


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/audit-filter-presets/"),
        ("post", "/api/audit-filter-presets/"),
        ("post", "/api/python-code-tool/1/favorite/"),
        ("delete", "/api/mcp-tools/1/favorite/"),
        ("get", "/api/flow-assistants/1/"),
        ("get", "/api/flow-assistants/1/conversations/"),
        ("get", "/api/flow-assistants/1/conversations/1/"),
        ("post", "/api/flow-assistants/1/conversations/1/messages/"),
        ("post", "/api/flow-assistants/1/conversations/1/cancel/"),
        ("get", "/api/flow-assistants/audit/conversations/"),
        ("post", "/api/init-realtime/"),
        ("post", "/api/notify/email/"),
    ],
)
def test_person_only_surfaces_refuse_a_plugin_credential(plugin_client, principal, method, path):
    response = getattr(plugin_client(principal), method)(path, {}, format="json")

    assert response.status_code == 403, response.content
    assert response.json()["code"] == "permission_denied"
    assert response.json()["message"] == PLUGIN_REFUSED


def test_purges_refuse_a_plugin_credential(plugin_client, principal):
    response = plugin_client(principal).post(
        "/api/secrets/recycle-bin/purge/", {"all": True}, format="json"
    )

    assert response.status_code == 403, response.content
    assert response.json()["message"] == PLUGIN_REFUSED


def test_plugin_credential_creates_a_secret_without_reading_it_back(plugin_client, principal, acme):
    response = plugin_client(principal).post(
        "/api/secrets/", {"name": "Fake key", "value": "s3cr3t-value"}, format="json"
    )

    assert response.status_code == 201, response.content
    assert "value" not in response.json()
    assert "s3cr3t-value" not in response.content.decode()
    assert response.json()["org"] == acme.id


@pytest.mark.parametrize("references_secrets", [True, False], ids=["allowed", "refused"])
def test_the_principal_decides_which_secrets_a_row_it_writes_may_reference(plugin_client, acme, references_secrets):
    secret = secret_service.create(text="sk-org", org=acme, name="ORG_KEY")
    principal = FakePinnedPrincipal(
        acme.id,
        by_resource={**DECLARED, ResourceType.LLM_CONFIGS: Permission.READ | Permission.CREATE},
        references_secrets=references_secrets,
    )

    response = plugin_client(principal).post(
        "/api/llm-configs/", {"custom_name": "Fake config", "api_key_secret_id": secret.pk}, format="json"
    )

    assert principal.secret_reference_questions == [frozenset({secret.pk})]
    assert response.status_code == (201 if references_secrets else 400), response.content


@pytest.mark.parametrize("write", ["create", "update"])
def test_a_pinned_principal_never_sets_where_a_model_sends_requests(plugin_client, acme, write):
    model = LLMModel.objects.create(name="acme-model", org=acme, is_custom=True)
    principal = FakePinnedPrincipal(
        acme.id, by_resource={**DECLARED, ResourceType.LLM_CONFIGS: Permission.READ | Permission.CREATE | Permission.UPDATE}
    )
    client = plugin_client(principal)

    if write == "create":
        response = client.post("/api/llm-models/", {"name": "fake-model", "base_url": "https://elsewhere.example"}, format="json")
    else:
        response = client.patch(f"/api/llm-models/{model.pk}/", {"deployment_id": "elsewhere"}, format="json")
    renamed = client.patch(f"/api/llm-models/{model.pk}/", {"name": "acme-model-2"}, format="json")

    assert response.status_code == 400, response.content
    assert renamed.status_code == 200, renamed.content


class _IncompletePrincipal(FakePinnedPrincipal):
    """Carries the plugin-credential flag but not all of `PinnedOrgPrincipal`."""

    may_reference_secrets = None


def _guarded_request(user, auth=None):
    request = APIRequestFactory().post("/")
    request.user, request.auth = user, auth
    return request


@pytest.mark.parametrize("flag_on", ["user", "credential"])
def test_a_plugin_credential_without_the_whole_protocol_is_refused_not_taken_for_a_person(acme, flag_on):
    secret = secret_service.create(text="sk-org", org=acme, name="ORG_KEY_2")
    if flag_on == "user":
        request = _guarded_request(_IncompletePrincipal(acme.id))
    else:
        person_shaped = SimpleNamespace(is_authenticated=True, is_plugin_credential=False)
        request = _guarded_request(person_shaped, auth=FakePluginKey())
    serializer = LLMConfigSerializer(context={"request": request})

    assert not is_pinned_org_principal(request.user)
    with pytest.raises(PermissionDenied):
        secret_reference_guard.assert_unchanged_or_permitted(
            serializer=serializer, attrs={"api_key_secret": secret}, fields=("api_key_secret_id",)
        )
    with pytest.raises(PermissionDenied):
        secret_destination_guard.assert_may_change_endpoints(
            serializer=LLMModelSerializer(context={"request": request}), attrs={"base_url": "https://x.example"}, fields=("base_url",)
        )


def test_user_api_key_is_still_refused_on_secrets(member_only, acme, issue_api_key):
    raw_key, _ = issue_api_key(user=member_only)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.get("/api/secrets/")

    assert response.status_code == 403, response.content
    assert response.json()["message"] == DenyPersonalAndSystemApiKeys.message


# ---- Tables code a pinned principal reaches ----


def test_tool_lists_show_no_favorites_to_a_pinned_principal(plugin_client, principal, acme):
    McpTool.objects.create(
        org=acme, name="fake-mcp", transport="https://example.com/mcp", tool_name="t"
    )
    client = plugin_client(principal)

    mcp_tools = client.get("/api/mcp-tools/?ordering=favorite")
    python_tools = client.get("/api/python-code-tool/?ordering=favorite")

    assert mcp_tools.status_code == 200, mcp_tools.content
    assert [tool["is_favorite"] for tool in mcp_tools.json()["results"]] == [False]
    assert python_tools.status_code == 200, python_tools.content
    assert all(tool["is_favorite"] is False for tool in python_tools.json()["results"])


def test_graph_user_is_the_on_behalf_of_persons(principal_for_member, member_only, acme):
    graph = Graph.objects.create(name="acme flow", org=acme)

    result = PersistentVariablesService().build_run_variables(graph, principal_for_member, {})

    assert result.graph_user == GraphOrganizationUser.objects.get(
        graph=graph, organization_user__user=member_only
    )


def test_autonomous_run_has_no_graph_user(principal, acme):
    graph = Graph.objects.create(name="acme flow", org=acme)

    result = PersistentVariablesService().build_run_variables(graph, principal, {})

    assert result.graph_user is None
    assert not GraphOrganizationUser.objects.filter(graph=graph).exists()


def test_run_on_behalf_of_a_person_records_a_plugin_principal(
    principal_for_member, member_only, acme, monkeypatch
):
    graph = Graph.objects.create(name="acme flow", org=acme)
    session_manager = _stub_publish(monkeypatch)

    session_id = session_manager.run_session(
        graph_id=graph.id,
        variables={},
        user=principal_for_member,
        api_key=None,
        trigger=TriggerSpec.manual(),
    )

    session = Session.objects.get(pk=session_id)
    assert session.graph_user.organization_user.user == member_only
    principal = session.principal
    assert principal.kind == SessionPrincipal.ActionKind.PLUGIN
    assert principal.plugin_identifier == "fakeplugin"
    assert principal.user == member_only
    assert principal.email == member_only.email
    assert principal.api_key is None


def test_autonomous_run_records_a_plugin_principal_without_a_person(principal, acme, monkeypatch):
    graph = Graph.objects.create(name="acme flow", org=acme)
    session_manager = _stub_publish(monkeypatch)

    session_id = session_manager.run_session(
        graph_id=graph.id, variables={}, user=principal, trigger=TriggerSpec.manual()
    )

    principal_row = Session.objects.get(pk=session_id).principal
    assert principal_row.kind == SessionPrincipal.ActionKind.PLUGIN
    assert principal_row.plugin_identifier == "fakeplugin"
    assert principal_row.user is None
    assert principal_row.email is None


def test_subflow_sessions_copy_the_plugin_principal(member_only, acme):
    root_graph = Graph.objects.create(name="root", org=acme)
    child_graph = Graph.objects.create(name="child", org=acme)
    root_session = Session.objects.create(
        graph=root_graph, status=Session.SessionStatus.END, variables={}
    )
    SessionPrincipal.objects.create(
        session=root_session,
        kind=SessionPrincipal.ActionKind.PLUGIN,
        plugin_identifier="fakeplugin",
        user=member_only,
        email=member_only.email,
    )
    for message_type, extra in (
        (
            "subgraph_start",
            {"subgraph_id": child_graph.id, "input": {}, "subgraph_execution_ids": []},
        ),
        ("subgraph_finish", {"output": {}}),
    ):
        GraphSessionMessage.objects.create(
            session=root_session,
            created_at=timezone.now(),
            uuid=uuid4(),
            message_data={"message_type": message_type, "subgraph_execution_id": "exec-1", **extra},
        )

    GraphMessageStore(fakeredis.FakeRedis()).create_subgraph_sessions(root_session.id)

    child_principal = Session.objects.get(parent_session=root_session).principal
    assert child_principal.kind == SessionPrincipal.ActionKind.PLUGIN
    assert child_principal.plugin_identifier == "fakeplugin"
    assert child_principal.user == member_only


def test_session_serializers_expose_the_plugin_identifier(member_only, acme):
    session = Session.objects.create(graph=Graph.objects.create(name="g", org=acme), variables={})
    principal_row = SessionPrincipal.objects.create(
        session=session,
        kind=SessionPrincipal.ActionKind.PLUGIN,
        plugin_identifier="fakeplugin",
        user=member_only,
        email=member_only.email,
    )

    assert SessionPrincipalSerializer(principal_row).data["plugin_identifier"] == "fakeplugin"
    assert SessionPrincipalExportSerializer(principal_row).data["plugin_identifier"] == "fakeplugin"


@pytest.mark.parametrize(
    ("email", "started_by"),
    [
        ("ada@example.com", "fakeplugin (plugin) on behalf of ada@example.com"),
        (None, "fakeplugin (plugin)"),
    ],
)
def test_tabular_export_names_the_plugin(email, started_by):
    item = {
        "session": {
            "id": 7,
            "principal": {"kind": "plugin", "plugin_identifier": "fakeplugin", "email": email},
        },
        "messages": [
            {
                "id": 1,
                "session_id": 7,
                "created_at": "2026-10-21T08:00:00Z",
                "name": "start",
                "execution_order": 0,
                "message_data": {"message_type": "start", "input": {}},
            }
        ],
    }

    [row] = SessionTabularProjection().expand(item)

    assert (row["started_by_type"], row["started_by"]) == ("plugin", started_by)


def test_editor_info_of_a_pinned_principal_has_no_user_id(principal):
    editor = build_editor_info(principal)

    assert editor.model_dump() == {
        "user_id": None,
        "display_name": "Fake (plugin)",
        "avatar_url": None,
    }


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
def test_graph_saved_by_a_pinned_principal_broadcasts_its_name(plugin_client, principal, acme):
    graph = Graph.objects.create(name="acme flow", org=acme)
    channel_layer = get_channel_layer()
    channel_name = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)(f"graph_edit_{graph.id}", channel_name)

    response = plugin_client(principal).patch(
        f"/api/graphs/{graph.id}/",
        {"name": "renamed", "save_version": graph.save_version},
        format="json",
    )

    assert response.status_code == 200, response.content
    message = async_to_sync(channel_layer.receive)(channel_name)
    assert message["type"] == "graph_saved"
    assert message["saved_by"] == {
        "user_id": None,
        "display_name": "Fake (plugin)",
        "avatar_url": None,
    }


def test_notify_email_throttle_keys_on_the_rate_limit_key(principal):
    request = SimpleNamespace(user=principal, META={})

    cache_key = NotifyEmailThrottle().get_cache_key(request, view=None)

    assert cache_key == f"throttle_notify_email_{principal.rate_limit_key}"


def test_storage_authenticates_with_the_project_defaults():
    # The upload stream app authenticates with these too, so both stay open to
    # every credential the API accepts.
    authenticators = StorageAPIView().get_authenticators()

    assert [type(authenticator) for authenticator in authenticators] == list(
        api_settings.DEFAULT_AUTHENTICATION_CLASSES
    )


def test_plugin_credential_never_purges_the_storage_bin(principal, acme):
    access = StorageBinPurgeAccess.for_request(_request(principal, FakePluginKey()), acme.id)

    assert access.grant is None
    assert access.names_visible is False


class TestRowsBulkCreated:
    @pytest.fixture
    def received(self):
        calls = []

        def receiver(sender, queryset, **kwargs):
            calls.append((sender, sorted(queryset.values_list("path", flat=True))))

        rows_bulk_created.connect(receiver)
        yield calls
        rows_bulk_created.disconnect(receiver)

    def test_bulk_upload_sends_the_inserted_file_rows_only(self, received, acme):
        StorageFile.objects.create(
            org=acme, path="docs/old.txt", name="old.txt", item_type="file", parent_path="docs/"
        )

        StorageFileSync.on_bulk_upload(
            acme.id, [("docs/old.txt", 3), ("docs/new.txt", 4), ("b/c/deep.txt", 5)], ["empty/"]
        )

        assert received == [(StorageFile, ["b/c/deep.txt", "docs/new.txt"])]

    @pytest.fixture
    def between_read_and_insert(self, monkeypatch):
        """Run a callable where on_bulk_upload has read the live rows but not inserted yet."""

        def _install(action):
            bulk_update = StorageFile.objects.bulk_update

            def bulk_update_then_act(*args, **kwargs):
                updated = bulk_update(*args, **kwargs)
                action()
                return updated

            monkeypatch.setattr(StorageFile.objects, "bulk_update", bulk_update_then_act)

        return _install

    def test_a_path_another_writer_takes_after_the_read_is_not_reported(
        self, received, acme, between_read_and_insert
    ):
        between_read_and_insert(
            lambda: StorageFile.objects.create(
                org=acme, path="docs/raced.txt", name="raced.txt", parent_path="docs/"
            )
        )

        StorageFileSync.on_bulk_upload(acme.id, [("docs/raced.txt", 3), ("docs/new.txt", 4)])

        assert received == [(StorageFile, ["docs/new.txt"])]

    def test_a_path_binned_after_the_read_is_reported_once_recreated(
        self, received, acme, between_read_and_insert
    ):
        binned = StorageFile.objects.create(
            org=acme, path="docs/old.txt", name="old.txt", parent_path="docs/"
        )
        between_read_and_insert(
            lambda: StorageFile.objects.filter(pk=binned.pk).update(
                active=False, soft_deleted_at=timezone.now(), soft_delete_batch=uuid4()
            )
        )

        StorageFileSync.on_bulk_upload(acme.id, [("docs/old.txt", 3)])

        assert received == [(StorageFile, ["docs/old.txt"])]
        assert StorageFile.objects.get(org=acme, path="docs/old.txt").pk != binned.pk

    def test_bulk_upload_of_existing_files_only_sends_nothing(self, received, acme):
        StorageFile.objects.create(
            org=acme, path="old.txt", name="old.txt", item_type="file", parent_path=""
        )

        StorageFileSync.on_bulk_upload(acme.id, [("old.txt", 3)], ["new-folder/"])

        assert received == []
