"""Plugin dev mode: one admin loads an installed plugin's page from a localhost dev server."""

import pytest

from plugins.models import Plugin
from rbac.models import Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tests.plugins_tests.helpers import PLUGINS_URL, plugin_url

DEV_URL = "http://localhost:4300/"


@pytest.fixture
def dev_mode(settings):
    settings.PLUGINS_DEV_MODE = True
    yield settings


def _set(client, plugin, url=DEV_URL):
    return client.post(plugin_url(plugin, "dev-ui"), {"url": url}, format="json")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [{"url": DEV_URL}, {"url": "https://evil.example/"}, {}],
    ids=["valid-url", "invalid-url", "no-url"],
)
def test_with_the_flag_off_setting_a_dev_url_is_409_and_stores_nothing(
    chat_admin_plugin, admin_client, settings, body
):
    settings.PLUGINS_DEV_MODE = False

    response = admin_client.post(plugin_url(chat_admin_plugin, "dev-ui"), body, format="json")

    assert response.status_code == 409, response.content
    assert response.json()["code"] == "plugin_dev_mode_disabled"
    chat_admin_plugin.refresh_from_db()
    assert (chat_admin_plugin.dev_ui_url, chat_admin_plugin.dev_ui_user_id) == ("", None)


@pytest.mark.django_db
def test_setting_a_dev_url_binds_it_to_the_caller(
    chat_admin_plugin, admin_client, admin_acme, dev_mode
):
    response = _set(admin_client, chat_admin_plugin)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["dev_mode_available"] is True
    assert body["dev_ui_url"] == DEV_URL
    assert body["dev_ui_user"] == admin_acme.pk
    chat_admin_plugin.refresh_from_db()
    assert chat_admin_plugin.dev_ui_url == DEV_URL
    assert chat_admin_plugin.dev_ui_user_id == admin_acme.pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:4300/",
        "http://127.0.0.1:4300/",
        "http://localhost",
        "http://localhost:4300",
        "http://localhost:4300/apps/chat/index.html",
        "http://localhost:4300/a%20b/~x_y-z.html",
        "http://localhost:65535/",
    ],
)
def test_plain_http_urls_on_localhost_are_accepted(chat_admin_plugin, admin_client, dev_mode, url):
    assert _set(admin_client, chat_admin_plugin, url).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "https://localhost:4300/",
        "http://localhost.evil.com:4300/",
        "http://evil.com/",
        "http://user@localhost:4300/",
        "http://user:secret@localhost/",
        "http://localhost:4300/?debug=1",
        "http://localhost:4300/#/chat",
        "http://localhost:4300/\n",
        " http://localhost:4300/",
        "http://localhost:0/",
        "http://localhost:70000/",
        "http://[::1]:4300/",
        "http://LOCALHOST:4300/",
        "javascript:alert(1)",
        "//localhost:4300/",
        "",
        "http://localhost:4300/" + "a" * 240,
        # Arabic-Indic and full-width digits: int() reads them as 4300.
        "http://localhost:\u0664\u0663\u0660\u0660/",
        "http://localhost:\uff14\uff13\uff10\uff10/",
    ],
)
def test_anything_else_is_400_invalid(chat_admin_plugin, admin_client, dev_mode, url):
    response = _set(admin_client, chat_admin_plugin, url)

    assert response.status_code == 400, response.content
    assert response.json()["code"] == "invalid"
    chat_admin_plugin.refresh_from_db()
    assert chat_admin_plugin.dev_ui_url == ""


@pytest.mark.django_db
@pytest.mark.parametrize("body", [{}, {"url": None}], ids=["missing", "null"])
def test_a_missing_url_is_400_invalid(chat_admin_plugin, admin_client, dev_mode, body):
    response = admin_client.post(plugin_url(chat_admin_plugin, "dev-ui"), body, format="json")

    assert response.status_code == 400, response.content
    assert response.json()["code"] == "invalid"


@pytest.mark.django_db
def test_a_member_gets_403(chat_admin_plugin, acme, member_of, org_client, role_member, dev_mode):
    client = org_client(member_of(acme, role_member, "member@acme.test"), acme)

    assert _set(client, chat_admin_plugin).status_code == 403
    assert client.delete(plugin_url(chat_admin_plugin, "dev-ui")).status_code == 403


@pytest.mark.django_db
def test_using_a_plugin_is_not_enough_to_set_its_dev_url(
    chat_admin_plugin, acme, member_of, org_client, dev_mode
):
    role = Role.objects.create(name="Plugin user", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.PLUGINS.value,
        permissions=int(Permission.READ | Permission.USE),
    )
    client = org_client(member_of(acme, role, "user@acme.test"), acme)

    assert _set(client, chat_admin_plugin).status_code == 403
    assert client.delete(plugin_url(chat_admin_plugin, "dev-ui")).status_code == 403


@pytest.fixture
def second_admin_client(acme, role_org_admin, member_of, org_client):
    yield org_client(member_of(acme, role_org_admin, "admin2@acme.test"), acme)


@pytest.mark.django_db
def test_only_the_admin_who_set_it_gets_the_dev_page(
    chat_admin_plugin, admin_client, second_admin_client, dev_mode
):
    _set(admin_client, chat_admin_plugin)

    own = admin_client.post(plugin_url(chat_admin_plugin, "ui-session")).json()
    other = second_admin_client.post(plugin_url(chat_admin_plugin, "ui-session")).json()

    assert own["url"] == DEV_URL
    assert (own["token"], own["expires_in"], own["dev_mode"]) == ("", None, True)
    assert own["bridge_version"] == 2
    assert [entry["alias"] for entry in own["access"]] == ["chat", "conversations"]
    assert other["dev_mode"] is False
    assert other["url"] == f"/api/plugin-ui/{other['token']}/index.html"
    assert other["expires_in"] == 43200


@pytest.mark.django_db
def test_turning_the_flag_off_serves_the_installed_page_again(
    chat_admin_plugin, admin_client, dev_mode
):
    _set(admin_client, chat_admin_plugin)
    dev_mode.PLUGINS_DEV_MODE = False

    session = admin_client.post(plugin_url(chat_admin_plugin, "ui-session")).json()
    detail = admin_client.get(plugin_url(chat_admin_plugin)).json()

    assert session["dev_mode"] is False
    assert session["url"].startswith("/api/plugin-ui/")
    assert detail["dev_mode_available"] is False


@pytest.mark.django_db
def test_a_suspended_plugin_does_not_open_in_dev_mode_either(
    chat_admin_plugin, admin_client, dev_mode
):
    _set(admin_client, chat_admin_plugin)
    Plugin.objects.filter(pk=chat_admin_plugin.pk).update(suspended=True)

    response = admin_client.post(plugin_url(chat_admin_plugin, "ui-session"))

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_suspended"


@pytest.mark.django_db
@pytest.mark.parametrize("flag", [True, False], ids=["flag-on", "flag-off"])
def test_delete_clears_the_dev_url_even_with_the_flag_off(
    chat_admin_plugin, admin_client, admin_acme, settings, flag
):
    Plugin.objects.filter(pk=chat_admin_plugin.pk).update(dev_ui_url=DEV_URL, dev_ui_user=admin_acme)
    settings.PLUGINS_DEV_MODE = flag

    response = admin_client.delete(plugin_url(chat_admin_plugin, "dev-ui"))

    assert response.status_code == 200, response.content
    assert (response.json()["dev_ui_url"], response.json()["dev_ui_user"]) == (None, None)
    session = admin_client.post(plugin_url(chat_admin_plugin, "ui-session")).json()
    assert session["dev_mode"] is False


@pytest.mark.django_db
@pytest.mark.parametrize("flag", [True, False], ids=["flag-on", "flag-off"])
def test_list_and_detail_report_the_dev_fields(chat_admin_plugin, admin_client, admin_acme, settings, flag):
    settings.PLUGINS_DEV_MODE = flag
    Plugin.objects.filter(pk=chat_admin_plugin.pk).update(dev_ui_url=DEV_URL, dev_ui_user=admin_acme)

    [listed] = admin_client.get(PLUGINS_URL).json()
    detail = admin_client.get(plugin_url(chat_admin_plugin)).json()

    for body in (listed, detail):
        assert body["dev_mode_available"] is flag
        assert body["dev_ui_url"] == DEV_URL
        assert body["dev_ui_user"] == admin_acme.pk


@pytest.mark.django_db
def test_a_plugin_without_a_dev_url_reports_nulls(installed_plugin, admin_client):
    body = admin_client.get(plugin_url(installed_plugin)).json()

    assert (body["dev_mode_available"], body["dev_ui_url"], body["dev_ui_user"]) == (False, None, None)


@pytest.mark.django_db
def test_deleting_the_dev_admin_clears_the_dev_user(
    chat_admin_plugin, admin_client, admin_acme, second_admin_client, dev_mode
):
    _set(admin_client, chat_admin_plugin)
    admin_acme.delete()

    chat_admin_plugin.refresh_from_db()
    session = second_admin_client.post(plugin_url(chat_admin_plugin, "ui-session")).json()

    assert chat_admin_plugin.dev_ui_user_id is None
    assert session["dev_mode"] is False


@pytest.mark.django_db
def test_another_orgs_admin_gets_404(
    chat_admin_plugin, beta, role_org_admin, member_of, org_client, dev_mode
):
    client = org_client(member_of(beta, role_org_admin, "admin@beta.test"), beta)

    assert _set(client, chat_admin_plugin).status_code == 404
    assert client.delete(plugin_url(chat_admin_plugin, "dev-ui")).status_code == 404
    chat_admin_plugin.refresh_from_db()
    assert chat_admin_plugin.dev_ui_url == ""
