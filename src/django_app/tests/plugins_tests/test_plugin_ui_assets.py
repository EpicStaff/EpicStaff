import hashlib
import time

import pytest
from django.core import signing

from plugins.models import Plugin, PluginAsset
from plugins.samples.zip_builder import sample_files
from plugins.services import ui_token
from plugins.services.ui_service import _content_type
from plugins.services.ui_token import UiTokenClaims
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tests.plugins_tests.helpers import plugin_url, registered_ids

CSP = (
    "sandbox allow-scripts; default-src 'none'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'none'; frame-src 'none'; worker-src 'none'; "
    "object-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'"
)

EXTRA_ASSETS = {
    "css/style.css": b"body { color: black; }",
    "logo.png": b"\x89PNG\r\n\x1a\nrest",
    "strings.json": b'{"hello": "world"}',
}


@pytest.fixture
def page_plugin(ready_plugin):
    """The ready sample, with one asset of every allowed type."""
    PluginAsset.objects.bulk_create(
        [
            PluginAsset(
                plugin=ready_plugin,
                path=path,
                content_type="ignored/by-the-view",
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
            )
            for path, content in EXTRA_ASSETS.items()
        ]
    )
    yield ready_plugin


@pytest.fixture
def token_for(page_plugin, admin_acme):
    def _make(user=admin_acme, plugin=page_plugin, org_id=None) -> str:
        return ui_token.issue(
            UiTokenClaims(plugin_pk=plugin.pk, org_id=org_id or plugin.org_id, user_id=user.pk)
        )

    yield _make


def _asset_url(token: str, path: str) -> str:
    return f"/api/plugin-ui/{token}/{path}"


# --- ui-session --------------------------------------------------------------------


@pytest.mark.django_db
def test_ui_session_returns_a_page_url_with_a_short_lived_token(page_plugin, admin_client):
    response = admin_client.post(plugin_url(page_plugin, "ui-session"))

    assert response.status_code == 200, response.content
    body = response.json()
    [flow_id] = registered_ids(page_plugin, "flow")
    assert body["url"] == f"/api/plugin-ui/{body['token']}/index.html"
    assert body["expires_in"] == 600
    assert body["bridge_version"] == 1
    assert body["plugin"] == {
        "id": page_plugin.pk,
        "plugin_id": "chat-bot",
        "name": "Chat Bot",
        "version": "0.1.0",
    }
    assert body["access"] == [
        {
            "alias": "chat",
            "type": "flow",
            "actions": ["run", "sessions.read", "sessions.stop"],
            "resource_id": flow_id,
        }
    ]
    assert "Set-Cookie" not in response
    page = admin_client.get(body["url"])
    assert page.status_code == 200
    assert page.content == sample_files()["ui/index.html"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "changes, code",
    [
        ({"suspended": True}, "plugin_suspended"),
        ({"state": Plugin.State.NEEDS_ATTENTION}, "plugin_not_ready"),
        ({"ui_entry": ""}, "plugin_has_no_ui"),
    ],
)
def test_ui_session_refuses_a_plugin_whose_page_cannot_open(
    page_plugin, admin_client, changes, code
):
    Plugin.objects.filter(pk=page_plugin.pk).update(**changes)

    response = admin_client.post(plugin_url(page_plugin, "ui-session"))

    assert response.status_code == 409
    assert response.json()["code"] == code


@pytest.mark.django_db
def test_ui_session_refuses_a_plugin_still_preparing(installed_plugin, admin_client):
    response = admin_client.post(plugin_url(installed_plugin, "ui-session"))

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_not_ready"


@pytest.mark.django_db
def test_ui_session_needs_use(page_plugin, acme, member_of, org_client):
    reader = Role.objects.create(name="Plugin reader", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=reader, resource_type=ResourceType.PLUGINS.value, permissions=int(Permission.READ)
    )
    user = Role.objects.create(name="Plugin user", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=user, resource_type=ResourceType.PLUGINS.value, permissions=int(Permission.USE)
    )

    refused = org_client(member_of(acme, reader, "reader@acme.test"), acme)
    allowed = org_client(member_of(acme, user, "user@acme.test"), acme)

    assert refused.post(plugin_url(page_plugin, "ui-session")).status_code == 403
    assert allowed.post(plugin_url(page_plugin, "ui-session")).status_code == 200


# --- serving files -----------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path, content_type",
    [
        ("index.html", "text/html; charset=utf-8"),
        ("app.js", "text/javascript; charset=utf-8"),
        ("css/style.css", "text/css; charset=utf-8"),
        ("icon.svg", "image/svg+xml"),
        ("logo.png", "image/png"),
        ("strings.json", "application/json"),
    ],
)
def test_assets_are_served_with_the_locked_down_headers(
    page_plugin, token_for, client, path, content_type
):
    response = client.get(_asset_url(token_for(), path))

    assert response.status_code == 200
    assert response["Content-Type"] == content_type
    assert response["Content-Security-Policy"] == CSP
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["Cross-Origin-Resource-Policy"] == "cross-origin"
    assert response["X-Frame-Options"] == "SAMEORIGIN"
    assert "Set-Cookie" not in response
    assert not response.cookies
    assert "Cookie" not in response.get("Vary", "")
    expected = EXTRA_ASSETS.get(path) or sample_files()[f"ui/{path}"]
    assert response.content == expected


@pytest.mark.django_db
def test_the_token_is_reusable_for_every_file_of_the_page(page_plugin, token_for, client):
    token = token_for()

    for path in ("index.html", "app.js", "css/style.css"):
        assert client.get(_asset_url(token, path)).status_code == 200


def _expired_token(page_plugin, admin_acme) -> str:
    stale = int(time.time()) - ui_token.MAX_AGE_SECONDS - 1
    signer = signing.TimestampSigner(salt=ui_token.SALT)
    signer.timestamp = lambda: signing.b62_encode(stale)
    return signer.sign_object(
        {"plugin": page_plugin.pk, "org": page_plugin.org_id, "user": admin_acme.pk}
    )


def _forged_token(page_plugin, admin_acme) -> str:
    genuine = ui_token.issue(UiTokenClaims(page_plugin.pk, page_plugin.org_id, admin_acme.pk))
    payload, timestamp, signature = genuine.split(":")
    return f"{payload}:{timestamp}:{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"


def _unsalted_token(page_plugin, admin_acme) -> str:
    return signing.dumps({"plugin": page_plugin.pk, "org": page_plugin.org_id, "user": admin_acme.pk})


@pytest.mark.django_db
@pytest.mark.parametrize("make_token", [_expired_token, _forged_token, _unsalted_token])
def test_a_bad_token_is_404(page_plugin, admin_acme, client, make_token):
    response = client.get(_asset_url(make_token(page_plugin, admin_acme), "index.html"))

    assert response.status_code == 404
    assert response.content == b""


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "../index.html",
        "css/../index.html",
        "%2e%2e/index.html",
        "./index.html",
        "css//style.css",
        "missing.js",
        "index.HTML",
        "notes.txt",
    ],
)
def test_a_path_that_is_not_exactly_one_of_the_plugins_files_is_404(
    page_plugin, token_for, client, path
):
    PluginAsset.objects.create(
        plugin=page_plugin, path="notes.txt", content_type="text/plain", content=b"x", sha256="0"
    )

    assert client.get(_asset_url(token_for(), path)).status_code == 404


@pytest.mark.django_db
def test_a_file_of_another_plugin_is_404(page_plugin, token_for, client, acme):
    other = Plugin.objects.create(
        org=acme, plugin_id="other", version="1.0.0", format_version=1, bridge_version=1,
        name="Other", ui_entry="index.html", state=Plugin.State.READY,
    )
    PluginAsset.objects.create(
        plugin=other, path="secret.js", content_type="text/javascript", content=b"x", sha256="0"
    )

    assert client.get(_asset_url(token_for(), "secret.js")).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    "changes",
    [{"suspended": True}, {"state": Plugin.State.NEEDS_ATTENTION}, {"state": Plugin.State.PREPARING}],
    ids=["suspended", "needs_attention", "preparing"],
)
def test_a_plugin_that_cannot_run_serves_nothing(page_plugin, token_for, client, changes):
    token = token_for()
    Plugin.objects.filter(pk=page_plugin.pk).update(**changes)

    assert client.get(_asset_url(token, "index.html")).status_code == 404


@pytest.mark.django_db
def test_a_token_naming_another_org_is_404(page_plugin, token_for, client, beta):
    assert client.get(_asset_url(token_for(org_id=beta.pk), "index.html")).status_code == 404


@pytest.mark.django_db
def test_a_deleted_plugin_serves_nothing(page_plugin, token_for, client):
    token = token_for()
    Plugin.objects.filter(pk=page_plugin.pk).delete()

    assert client.get(_asset_url(token, "index.html")).status_code == 404


@pytest.mark.django_db
def test_a_user_without_plugins_use_is_404(page_plugin, token_for, client, acme, member_of, role_member):
    member = member_of(acme, role_member, "member@acme.test")

    assert client.get(_asset_url(token_for(user=member), "index.html")).status_code == 404


@pytest.mark.django_db
def test_a_user_who_loses_use_after_the_token_was_issued_is_404(
    page_plugin, token_for, client, admin_acme, acme, role_member
):
    token = token_for()
    assert client.get(_asset_url(token, "index.html")).status_code == 200

    OrganizationUser.objects.filter(user=admin_acme, org=acme).update(role=role_member)

    assert client.get(_asset_url(token, "index.html")).status_code == 404


@pytest.mark.django_db
def test_a_user_removed_from_the_org_is_404(page_plugin, token_for, client, admin_acme, acme):
    token = token_for()
    OrganizationUser.objects.filter(user=admin_acme, org=acme).delete()

    assert client.get(_asset_url(token, "index.html")).status_code == 404


@pytest.mark.django_db
def test_assets_ignore_cookies_and_bearer_credentials(page_plugin, admin_client, client):
    """Only the token authorizes: a signed-in caller without one gets nothing."""
    assert admin_client.get(_asset_url("not-a-token", "index.html")).status_code == 404


def test_tokens_carry_only_ids_and_round_trip():
    token = ui_token.issue(UiTokenClaims(plugin_pk=7, org_id=3, user_id=5))

    assert ui_token.read(token) == UiTokenClaims(7, 3, 5)
    assert signing.loads(token, salt=ui_token.SALT) == {"plugin": 7, "org": 3, "user": 5}


@pytest.mark.parametrize(
    "path, served_as",
    [
        ("index.html", "text/html; charset=utf-8"),
        ("css/style.css", "text/css; charset=utf-8"),
        ("css/../index.html", None),
        ("../index.html", None),
        ("./index.html", None),
        ("a//b.js", None),
        ("a\\b.js", None),
        ("/index.html", None),
        ("index.html\x00.png", None),
        ("notes.txt", None),
        ("", None),
    ],
)
def test_only_canonical_paths_of_allowed_types_are_served(path, served_as):
    assert _content_type(path) == served_as
