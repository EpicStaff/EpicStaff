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
    "sandbox allow-scripts; default-src 'none'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
    "connect-src 'none'; media-src 'none'; frame-src 'none'; worker-src 'none'; "
    "manifest-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'; "
    "frame-ancestors 'self'"
)
TWELVE_HOURS = 12 * 60 * 60
# What a browser sends when the host page's sandboxed iframe loads a plugin document.
FRAME = {"HTTP_SEC_FETCH_DEST": "iframe", "HTTP_SEC_FETCH_MODE": "navigate"}

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
def test_ui_session_returns_a_page_url_with_a_twelve_hour_token(page_plugin, admin_client):
    response = admin_client.post(plugin_url(page_plugin, "ui-session"))

    assert response.status_code == 200, response.content
    body = response.json()
    [flow_id] = registered_ids(page_plugin, "flow")
    assert body["url"] == f"/api/plugin-ui/{body['token']}/index.html"
    assert body["expires_in"] == TWELVE_HOURS
    assert body["dev_mode"] is False
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
    page = admin_client.get(body["url"], **FRAME)
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
    response = client.get(_asset_url(token_for(), path), **FRAME)

    assert response.status_code == 200
    assert response["Content-Type"] == content_type
    assert response["Content-Security-Policy"] == CSP
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["Cross-Origin-Resource-Policy"] == "cross-origin"
    assert response["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Credentials" not in response
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
        assert client.get(_asset_url(token, path), **FRAME).status_code == 200


def _expired_token(page_plugin, admin_acme) -> str:
    stale = int(time.time()) - ui_token.MAX_AGE_SECONDS - 1
    signer = signing.TimestampSigner(salt=ui_token.SALT)
    signer.timestamp = lambda: signing.b62_encode(stale)
    return signer.sign_object(
        {"plugin": page_plugin.pk, "org": page_plugin.org_id, "user": admin_acme.pk}
    )


def _token_issued_ago(seconds: int, page_plugin, admin_acme) -> str:
    signer = signing.TimestampSigner(salt=ui_token.SALT)
    signer.timestamp = lambda: signing.b62_encode(int(time.time()) - seconds)
    return signer.sign_object(
        {"plugin": page_plugin.pk, "org": page_plugin.org_id, "user": admin_acme.pk}
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "age, status",
    [(TWELVE_HOURS - 60, 200), (TWELVE_HOURS + 1, 404)],
    ids=["just-under-12h", "just-over-12h"],
)
def test_a_token_lasts_twelve_hours(page_plugin, admin_acme, client, age, status):
    token = _token_issued_ago(age, page_plugin, admin_acme)

    assert client.get(_asset_url(token, "index.html"), **FRAME).status_code == status


def _forged_token(page_plugin, admin_acme) -> str:
    genuine = ui_token.issue(UiTokenClaims(page_plugin.pk, page_plugin.org_id, admin_acme.pk))
    payload, timestamp, signature = genuine.split(":")
    return f"{payload}:{timestamp}:{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"


def _unsalted_token(page_plugin, admin_acme) -> str:
    return signing.dumps({"plugin": page_plugin.pk, "org": page_plugin.org_id, "user": admin_acme.pk})


@pytest.mark.django_db
@pytest.mark.parametrize("make_token", [_expired_token, _forged_token, _unsalted_token])
def test_a_bad_token_is_404(page_plugin, admin_acme, client, make_token):
    response = client.get(_asset_url(make_token(page_plugin, admin_acme), "index.html"), **FRAME)

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
        "notes.md",
    ],
)
def test_a_path_that_is_not_exactly_one_of_the_plugins_files_is_404(
    page_plugin, token_for, client, path
):
    PluginAsset.objects.create(
        plugin=page_plugin, path="notes.md", content_type="text/plain", content=b"x", sha256="0"
    )

    assert client.get(_asset_url(token_for(), path), **FRAME).status_code == 404


@pytest.mark.django_db
def test_a_file_of_another_plugin_is_404(page_plugin, token_for, client, acme):
    other = Plugin.objects.create(
        org=acme, plugin_id="other", version="1.0.0", format_version=1, bridge_version=1,
        name="Other", ui_entry="index.html", state=Plugin.State.READY,
    )
    PluginAsset.objects.create(
        plugin=other, path="secret.js", content_type="text/javascript", content=b"x", sha256="0"
    )

    assert client.get(_asset_url(token_for(), "secret.js"), **FRAME).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    "changes",
    [{"suspended": True}, {"state": Plugin.State.NEEDS_ATTENTION}, {"state": Plugin.State.PREPARING}],
    ids=["suspended", "needs_attention", "preparing"],
)
def test_a_plugin_that_cannot_run_serves_nothing(page_plugin, token_for, client, changes):
    token = token_for()
    Plugin.objects.filter(pk=page_plugin.pk).update(**changes)

    assert client.get(_asset_url(token, "index.html"), **FRAME).status_code == 404


@pytest.mark.django_db
def test_a_token_naming_another_org_is_404(page_plugin, token_for, client, beta):
    assert client.get(_asset_url(token_for(org_id=beta.pk), "index.html"), **FRAME).status_code == 404


@pytest.mark.django_db
def test_a_deleted_plugin_serves_nothing(page_plugin, token_for, client):
    token = token_for()
    Plugin.objects.filter(pk=page_plugin.pk).delete()

    assert client.get(_asset_url(token, "index.html"), **FRAME).status_code == 404


@pytest.mark.django_db
def test_a_user_without_plugins_use_is_404(page_plugin, token_for, client, acme, member_of, role_member):
    member = member_of(acme, role_member, "member@acme.test")

    assert client.get(_asset_url(token_for(user=member), "index.html"), **FRAME).status_code == 404


@pytest.mark.django_db
def test_a_user_who_loses_use_after_the_token_was_issued_is_404(
    page_plugin, token_for, client, admin_acme, acme, role_member
):
    token = token_for()
    assert client.get(_asset_url(token, "index.html"), **FRAME).status_code == 200

    OrganizationUser.objects.filter(user=admin_acme, org=acme).update(role=role_member)

    assert client.get(_asset_url(token, "index.html"), **FRAME).status_code == 404


@pytest.mark.django_db
def test_a_user_removed_from_the_org_is_404(page_plugin, token_for, client, admin_acme, acme):
    token = token_for()
    OrganizationUser.objects.filter(user=admin_acme, org=acme).delete()

    assert client.get(_asset_url(token, "index.html"), **FRAME).status_code == 404


@pytest.mark.django_db
def test_assets_ignore_cookies_and_bearer_credentials(page_plugin, admin_client, client):
    """Only the token authorizes: a signed-in caller without one gets nothing."""
    assert admin_client.get(_asset_url("not-a-token", "index.html"), **FRAME).status_code == 404


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
        ("notes.md", None),
        ("app.wasm", None),
        ("", None),
    ],
)
def test_only_canonical_paths_of_allowed_types_are_served(path, served_as):
    assert _content_type(path) == served_as


# Every type a framework build emits, served as the frozen contract says. Spelled out
# here, not read from UI_CONTENT_TYPES, so a changed mapping fails this test.
SERVED_TYPES = [
    ("index.html", "text/html; charset=utf-8"),
    ("main-ABC123.js", "text/javascript; charset=utf-8"),
    ("chunk-XYZ.mjs", "text/javascript; charset=utf-8"),
    ("styles-1.css", "text/css; charset=utf-8"),
    ("data.json", "application/json"),
    ("main.js.map", "application/json"),
    ("3rdpartylicenses.txt", "text/plain; charset=utf-8"),
    ("icon.svg", "image/svg+xml"),
    ("media/logo.png", "image/png"),
    ("media/photo.jpg", "image/jpeg"),
    ("media/photo.jpeg", "image/jpeg"),
    ("media/anim.gif", "image/gif"),
    ("media/pic.webp", "image/webp"),
    ("favicon.ico", "image/x-icon"),
    ("media/inter.woff", "font/woff"),
    ("media/inter-latin-400.woff2", "font/woff2"),
    ("media/inter.ttf", "font/ttf"),
    ("media/inter.otf", "font/otf"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("path, content_type", SERVED_TYPES)
def test_every_framework_build_file_type_is_served_with_its_type(
    page_plugin, token_for, client, path, content_type
):
    PluginAsset.objects.update_or_create(
        plugin=page_plugin,
        path=path,
        defaults={"content_type": "ignored/by-the-view", "content": b"x", "sha256": "0"},
    )

    response = client.get(_asset_url(token_for(), path), **FRAME)

    assert response.status_code == 200
    assert response["Content-Type"] == content_type
    assert response["Content-Security-Policy"] == CSP
    assert response["Access-Control-Allow-Origin"] == "*"


# --- Fetch Metadata: documents load only inside the frame ---------------------------


def _fetch_headers(dest: str | None, mode: str | None) -> dict:
    headers = {}
    if dest is not None:
        headers["HTTP_SEC_FETCH_DEST"] = dest
    if mode is not None:
        headers["HTTP_SEC_FETCH_MODE"] = mode
    return headers


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path, dest, mode",
    [
        ("index.html", "iframe", "navigate"),
        ("index.html", "iframe", "nested-navigate"),
        ("app.js", "script", "no-cors"),
        ("app.js", "script", "cors"),
        ("css/style.css", "style", "no-cors"),
        ("strings.json", "empty", "cors"),
        ("icon.svg", "image", "no-cors"),
        ("logo.png", "image", "no-cors"),
        ("index.html", "empty", "cors"),
    ],
    ids=[
        "frame-loads-the-page",
        "frame-navigates-within-itself",
        "classic-script",
        "module-script",
        "stylesheet",
        "fetch-json",
        "svg-as-image",
        "png-as-image",
        "page-fetches-an-html-template",
    ],
)
def test_the_frame_and_its_subresources_load(page_plugin, token_for, client, path, dest, mode):
    response = client.get(_asset_url(token_for(), path), **_fetch_headers(dest, mode))

    assert response.status_code == 200


@pytest.mark.django_db
def test_a_font_loads_as_a_subresource(page_plugin, token_for, client):
    PluginAsset.objects.create(
        plugin=page_plugin, path="media/inter.woff2", content_type="x", content=b"x", sha256="0"
    )

    response = client.get(
        _asset_url(token_for(), "media/inter.woff2"), **_fetch_headers("font", "cors")
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "font/woff2"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path, dest, mode",
    [
        ("index.html", "document", "navigate"),
        ("index.html", None, "navigate"),
        ("index.html", "frame", "nested-navigate"),
        ("index.html", "embed", "navigate"),
        ("icon.svg", "document", "navigate"),
        ("app.js", "document", "navigate"),
        ("index.html", None, None),
        ("icon.svg", None, None),
    ],
    ids=[
        "top-level-page",
        "navigation-without-a-destination",
        "legacy-frame",
        "navigation-into-an-embed",
        "top-level-svg",
        "top-level-script",
        "page-without-fetch-metadata",
        "svg-without-fetch-metadata",
    ],
)
def test_a_document_never_opens_outside_the_frame(page_plugin, token_for, client, path, dest, mode):
    response = client.get(_asset_url(token_for(), path), **_fetch_headers(dest, mode))

    assert response.status_code == 404
    assert response.content == b""
    assert "Content-Security-Policy" not in response


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["app.js", "css/style.css", "logo.png", "strings.json"])
def test_a_static_file_without_fetch_metadata_is_still_served(page_plugin, token_for, client, path):
    """curl and other tools send no Fetch Metadata; only documents need it."""
    assert client.get(_asset_url(token_for(), path)).status_code == 200


@pytest.mark.django_db
def test_a_navigation_is_refused_before_the_token_is_even_read(client, django_assert_num_queries):
    with django_assert_num_queries(0):
        response = client.get(
            _asset_url("not-a-token", "index.html"), **_fetch_headers("document", "navigate")
        )

    assert response.status_code == 404
