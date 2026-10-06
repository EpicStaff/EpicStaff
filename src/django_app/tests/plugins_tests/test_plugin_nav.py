import pytest

from plugins.models import Plugin
from rbac.models import Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tests.plugins_tests.helpers import PLUGINS_URL

NAV_URL = "/api/plugins/nav/"
ICON = "data:image/svg+xml;base64,PHN2Zy8+"


def _plugin(org, plugin_id: str, **fields) -> Plugin:
    defaults = {
        "version": "1.0.0",
        "format_version": 1,
        "bridge_version": 1,
        "name": plugin_id.replace("-", " ").title(),
        "ui_entry": "index.html",
        "state": Plugin.State.READY,
    }
    return Plugin.objects.create(org=org, plugin_id=plugin_id, **(defaults | fields))


@pytest.fixture
def client_with(acme, member_of, org_client):
    """Factory -> a client for a new Acme member whose role holds exactly `permissions` on plugins."""

    def _make(permissions: Permission, email: str):
        role = Role.objects.create(name=f"Plugins {email}", org=acme, is_built_in=False)
        RolePermission.objects.create(
            role=role, resource_type=ResourceType.PLUGINS.value, permissions=int(permissions)
        )
        return org_client(member_of(acme, role, email), acme)

    yield _make


@pytest.mark.django_db
def test_a_use_only_role_gets_the_nav_buttons_and_nothing_more(acme, client_with):
    with_icon = _plugin(acme, "chat-bot", name="Chat Bot", icon_data_url=ICON)
    without_icon = _plugin(acme, "notes", name="Notes")
    client = client_with(Permission.USE, "user@acme.test")

    response = client.get(NAV_URL)

    assert response.status_code == 200, response.content
    assert response.json() == [
        {"id": with_icon.pk, "name": "Chat Bot", "icon_data_url": ICON},
        {"id": without_icon.pk, "name": "Notes", "icon_data_url": None},
    ]
    # The full list stays behind plugins:read.
    assert client.get(PLUGINS_URL).status_code == 403


@pytest.mark.django_db
def test_a_read_only_role_gets_403(acme, client_with):
    _plugin(acme, "chat-bot")

    response = client_with(Permission.READ, "reader@acme.test").get(NAV_URL)

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


@pytest.mark.django_db
@pytest.mark.parametrize("role_fixture", ["role_member", "role_viewer"])
def test_member_and_viewer_get_403(request, role_fixture, acme, member_of, org_client):
    user = member_of(acme, request.getfixturevalue(role_fixture), f"{role_fixture}@acme.test")

    assert org_client(user, acme).get(NAV_URL).status_code == 403


@pytest.mark.django_db
def test_only_ready_running_plugins_with_a_page_are_listed(
    acme, installed_plugin, admin_client
):
    shown = _plugin(acme, "shown")
    _plugin(acme, "suspended", suspended=True)
    _plugin(acme, "no-page", ui_entry="")
    _plugin(acme, "broken", state=Plugin.State.NEEDS_ATTENTION, status_reason="x")
    assert installed_plugin.state == Plugin.State.PREPARING

    response = admin_client.get(NAV_URL)

    assert response.status_code == 200, response.content
    assert [item["id"] for item in response.json()] == [shown.pk]


@pytest.mark.django_db
def test_another_orgs_plugins_are_never_listed(acme, beta, client_with):
    own = _plugin(acme, "chat-bot")
    _plugin(beta, "chat-bot")
    _plugin(beta, "beta-only")

    response = client_with(Permission.USE, "user@acme.test").get(NAV_URL)

    assert [item["id"] for item in response.json()] == [own.pk]
