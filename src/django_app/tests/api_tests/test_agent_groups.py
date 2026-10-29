"""Agent groups: flat agent-scope labels shared by agents and shared surfaces.

Covers the `agent-labels/` endpoint, the `group` FK on agent definitions and surfaces
(org-scoped, agent-scope only, shared surfaces only) and that deleting a group
un-groups its items instead of deleting them.
"""

import pytest

from agents.exceptions import SurfaceValidationError
from agents.models import AgentDefinition
from agents.models.surface_models import Surface
from agents.services.surface_service import SurfaceService
from rbac.models import OrganizationUser
from tables.models.label_models import Label
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

AGENT_LABELS_URL = "/api/agent-labels/"
AGENTS_URL = "/api/agent-definitions/"
SURFACES_URL = "/api/surfaces/"


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def viewer_acme(db, django_user_model, acme, role_viewer):
    user = django_user_model.objects.create_user(
        email="viewer-agent-groups@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_viewer)
    return user


@pytest.fixture
def acme_group(acme):
    return Label.objects.create(name="Sales", org=acme, scope=Label.Scope.AGENT)


@pytest.fixture
def beta_group(beta):
    return Label.objects.create(name="Sales", org=beta, scope=Label.Scope.AGENT)


def _rows(response):
    body = response.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


# ---- agent-labels endpoint ----


def test_create_agent_label_lands_in_agent_scope_of_active_org(acme_client, acme):
    response = acme_client.post(AGENT_LABELS_URL, {"name": "Sales"}, format="json")

    assert response.status_code == 201
    label = Label.objects.get(pk=response.data["id"])
    assert label.scope == Label.Scope.AGENT
    assert label.org_id == acme.id


def test_list_agent_labels_shows_only_agent_scope_of_active_org(acme_client, acme, beta_group):
    own_group = Label.objects.create(name="Support", org=acme, scope=Label.Scope.AGENT)
    flow_label = Label.objects.create(name="Flows", org=acme, scope=Label.Scope.FLOW)

    response = acme_client.get(AGENT_LABELS_URL)

    assert response.status_code == 200
    shown_ids = {row["id"] for row in _rows(response)}
    assert own_group.id in shown_ids
    assert flow_label.id not in shown_ids
    assert beta_group.id not in shown_ids


def test_rename_agent_label(acme_client, acme_group):
    response = acme_client.patch(
        f"{AGENT_LABELS_URL}{acme_group.id}/", {"name": "Marketing"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["name"] == "Marketing"
    acme_group.refresh_from_db()
    assert acme_group.name == "Marketing"


def test_delete_agent_label(acme_client, acme_group):
    response = acme_client.delete(f"{AGENT_LABELS_URL}{acme_group.id}/")

    assert response.status_code == 204
    assert not Label.objects.filter(pk=acme_group.id).exists()


# Built-in roles: Viewer has agents:read only; Member has agents create/read/update
# but not delete.
@pytest.mark.parametrize(
    ("user_fixture", "method", "on_detail", "body", "expected_status"),
    [
        ("viewer_acme", "get", True, None, 200),
        ("viewer_acme", "post", False, {"name": "Support"}, 403),
        ("viewer_acme", "patch", True, {"name": "Marketing"}, 403),
        ("viewer_acme", "delete", True, None, 403),
        ("member_only", "delete", True, None, 403),
    ],
)
def test_agent_label_permissions_by_builtin_role(
    request, client_as, acme, acme_group, user_fixture, method, on_detail, body, expected_status
):
    client = client_as(request.getfixturevalue(user_fixture))
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    url = f"{AGENT_LABELS_URL}{acme_group.id}/" if on_detail else AGENT_LABELS_URL

    response = getattr(client, method)(url, body, format="json")

    assert response.status_code == expected_status
    acme_group.refresh_from_db()
    assert acme_group.name == "Sales"
    assert list(Label.objects.filter(org=acme, scope=Label.Scope.AGENT)) == [acme_group]


def test_nested_agent_label_is_400(acme_client, acme_group):
    response = acme_client.post(
        AGENT_LABELS_URL, {"name": "Inner", "parent": acme_group.id}, format="json"
    )

    assert response.status_code == 400
    assert "parent" in response.data["message"]
    assert not Label.objects.filter(name="Inner").exists()


def test_patching_parent_onto_agent_label_is_400(acme_client, acme, acme_group):
    other_group = Label.objects.create(name="Support", org=acme, scope=Label.Scope.AGENT)

    response = acme_client.patch(
        f"{AGENT_LABELS_URL}{acme_group.id}/", {"parent": other_group.id}, format="json"
    )

    assert response.status_code == 400
    acme_group.refresh_from_db()
    assert acme_group.parent_id is None


@pytest.mark.parametrize(
    ("method", "body"),
    [("get", None), ("patch", {"name": "Taken over"}), ("delete", None)],
)
def test_another_orgs_agent_label_is_404(acme_client, beta_group, method, body):
    response = getattr(acme_client, method)(
        f"{AGENT_LABELS_URL}{beta_group.id}/", body, format="json"
    )

    assert response.status_code == 404
    beta_group.refresh_from_db()
    assert beta_group.name == "Sales"


# ---- agent definition group ----


def test_create_agent_with_group(acme_client, acme_group):
    response = acme_client.post(
        AGENTS_URL, {"name": "closer", "group": acme_group.id}, format="json"
    )

    assert response.status_code == 201
    assert response.data["group"] == acme_group.id
    assert AgentDefinition.objects.get(pk=response.data["id"]).group_id == acme_group.id


def test_patch_agent_group_and_clear_it(acme_client, acme, acme_group):
    agent = AgentDefinition.objects.create(name="closer", org=acme)

    grouped = acme_client.patch(f"{AGENTS_URL}{agent.id}/", {"group": acme_group.id}, format="json")
    ungrouped = acme_client.patch(f"{AGENTS_URL}{agent.id}/", {"group": None}, format="json")

    assert grouped.status_code == 200
    assert grouped.data["group"] == acme_group.id
    assert ungrouped.status_code == 200
    assert ungrouped.data["group"] is None


def test_patch_agent_without_group_keeps_it(acme_client, acme, acme_group):
    agent = AgentDefinition.objects.create(name="closer", org=acme, group=acme_group)

    response = acme_client.patch(
        f"{AGENTS_URL}{agent.id}/", {"description": "new"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["group"] == acme_group.id


def test_agent_group_from_another_org_is_invalid_pk(acme_client, acme, beta_group):
    response = acme_client.post(
        AGENTS_URL, {"name": "closer", "group": beta_group.id}, format="json"
    )

    assert response.status_code == 400
    assert "group: Invalid pk" in response.data["message"]
    assert not AgentDefinition.objects.filter(org=acme).exists()


@pytest.mark.parametrize("scope", [Label.Scope.FLOW, Label.Scope.TOOL])
def test_agent_group_of_another_scope_is_invalid_pk(acme_client, acme, scope):
    label = Label.objects.create(name="Other tree", org=acme, scope=scope)

    response = acme_client.post(AGENTS_URL, {"name": "closer", "group": label.id}, format="json")

    assert response.status_code == 400
    assert "group: Invalid pk" in response.data["message"]
    assert not AgentDefinition.objects.filter(org=acme).exists()


# ---- surface group ----


def test_create_shared_surface_with_group(acme_client, acme_group):
    response = acme_client.post(
        SURFACES_URL, {"name": "playbook", "group": acme_group.id}, format="json"
    )

    assert response.status_code == 201
    assert response.data["group"] == acme_group.id


def test_create_owned_surface_with_group_is_400(acme_client, acme, acme_group):
    agent = AgentDefinition.objects.create(name="closer", org=acme)

    response = acme_client.post(
        SURFACES_URL,
        {"name": "playbook", "owner_agent": agent.id, "group": acme_group.id},
        format="json",
    )

    assert response.status_code == 400
    assert "group" in response.data["message"]
    assert not Surface.objects.filter(org=acme).exists()


def test_patch_group_onto_owned_surface_is_400(acme_client, acme, acme_group):
    agent = AgentDefinition.objects.create(name="closer", org=acme)
    surface = Surface.objects.create(name="playbook", org=acme, owner_agent=agent)

    response = acme_client.patch(
        f"{SURFACES_URL}{surface.id}/", {"group": acme_group.id}, format="json"
    )

    assert response.status_code == 400
    surface.refresh_from_db()
    assert surface.group_id is None


def test_giving_grouped_shared_surface_an_owner_clears_its_group(acme_client, acme, acme_group):
    agent = AgentDefinition.objects.create(name="closer", org=acme)
    surface = Surface.objects.create(name="playbook", org=acme, group=acme_group)

    response = acme_client.patch(
        f"{SURFACES_URL}{surface.id}/", {"owner_agent": agent.id}, format="json"
    )

    assert response.status_code == 200
    assert response.data["owner_agent"] == agent.id
    assert response.data["group"] is None
    surface.refresh_from_db()
    assert surface.group_id is None


def test_patch_shared_surface_without_group_keeps_it(acme_client, acme, acme_group):
    surface = Surface.objects.create(name="playbook", org=acme, group=acme_group)

    response = acme_client.patch(
        f"{SURFACES_URL}{surface.id}/", {"instructions": "be brief"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["group"] == acme_group.id


def test_grouping_surface_owned_since_validation_is_rejected(acme, acme_group):
    surface = Surface.objects.create(name="playbook", org=acme)
    stale_surface = Surface.objects.get(pk=surface.pk)
    agent = AgentDefinition.objects.create(name="closer", org=acme)
    Surface.objects.filter(pk=surface.pk).update(owner_agent=agent)

    with pytest.raises(SurfaceValidationError):
        SurfaceService.update_surface(
            instance=stale_surface, validated_data={"group": acme_group}, partial=True
        )

    surface.refresh_from_db()
    assert surface.owner_agent_id == agent.id
    assert surface.group_id is None


def test_surface_group_from_another_org_is_invalid_pk(acme_client, acme, beta_group):
    response = acme_client.post(
        SURFACES_URL, {"name": "playbook", "group": beta_group.id}, format="json"
    )

    assert response.status_code == 400
    assert "group: Invalid pk" in response.data["message"]
    assert not Surface.objects.filter(org=acme).exists()


# ---- deleting a group ----


def test_deleting_group_ungroups_its_agents_and_surfaces(acme_client, acme, acme_group):
    agent = AgentDefinition.objects.create(name="closer", org=acme, group=acme_group)
    surface = Surface.objects.create(name="playbook", org=acme, group=acme_group)

    response = acme_client.delete(f"{AGENT_LABELS_URL}{acme_group.id}/")

    assert response.status_code == 204
    agent.refresh_from_db()
    surface.refresh_from_db()
    assert agent.group_id is None
    assert surface.group_id is None
