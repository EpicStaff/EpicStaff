"""Every plugin decision is logged with the acting SuperAdmin, like the governance services' actions."""

import hashlib

import jwt
import pytest
from loguru import logger as loguru_logger
from plugins.exceptions import UntrustedNotAcknowledgedError
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.models import GrantState, PluginGrant
from rest_framework.test import APIClient

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.login_helpers import (
    STATE,
    WEATHER_ORIGIN,
    authorize,
    code_for,
    exchange,
    pkce_pair,
    redirect_parts,
    session_cookie,
)
from tests.plugins_tests.package_builder import build_package, sample_manifest

pytestmark = pytest.mark.django_db

# utils.logger cuts a message at 200 characters; every line must fit with realistic values.
MAX_MESSAGE_LENGTH = 200


@pytest.fixture
def log_messages():
    """The formatted message of every log record written during the test."""
    messages = []
    sink_id = loguru_logger.add(lambda message: messages.append(message.record["message"]), level="INFO")
    yield messages
    loguru_logger.remove(sink_id)


def _lines(messages, prefix):
    return [message for message in messages if message.startswith(prefix)]


def _actor(user):
    return f"actor={user.email} (id {user.pk})"


def test_an_upload_names_the_superadmin_the_package_and_its_digest(installation, superadmin, log_messages, trusts_release_key):
    data = build_package(signed_with=trusts_release_key)

    package = installation.upload(upload_file(data), len(data), superadmin)

    [action, digest] = _lines(log_messages, "PluginInstallationService.upload")
    assert action == (
        f"PluginInstallationService.upload {_actor(superadmin)} package={package.pk} plugin=weather "
        f"version=0.1.0 size={len(data)} trust=trusted signer=release"
    )
    assert digest == (
        f"PluginInstallationService.upload package={package.pk} sha256={hashlib.sha256(data).hexdigest()}"
    )
    assert all(len(line) <= MAX_MESSAGE_LENGTH for line in (action, digest))


def test_replacing_a_pending_package_logs_what_was_replaced(installation, superadmin, log_messages):
    first_data = build_package()
    first = installation.upload(upload_file(first_data), len(first_data), superadmin)
    second_data = build_package(manifest=sample_manifest(version="0.1.1"))

    second = installation.upload(upload_file(second_data), len(second_data), superadmin)

    [action, digest] = _lines(log_messages, "PluginInstallationService.replace_pending")
    assert action == (
        f"PluginInstallationService.replace_pending {_actor(superadmin)} package={first.pk} "
        f"plugin=weather version=0.1.0 replaced_by={second.pk}"
    )
    assert digest == (
        f"PluginInstallationService.replace_pending package={first.pk} "
        f"sha256={hashlib.sha256(first_data).hexdigest()}"
    )


@pytest.mark.parametrize("acknowledged", [True, False])
def test_an_approval_logs_trust_signer_and_the_acknowledgement(
    installation, superadmin, log_messages, trusts_release_key, acknowledged
):
    data = build_package(signed_with=trusts_release_key)
    package = installation.upload(upload_file(data), len(data), superadmin)

    installation.approve(package.pk, superadmin, untrusted_acknowledged=acknowledged)

    [action, digest] = _lines(log_messages, "PluginInstallationService.approve")
    assert action == (
        f"PluginInstallationService.approve {_actor(superadmin)} package={package.pk} plugin=weather "
        f"version=0.1.0 trust=trusted signer=release untrusted_acknowledged={acknowledged}"
    )
    assert digest == f"PluginInstallationService.approve package={package.pk} sha256={package.sha256}"
    assert len(action) <= MAX_MESSAGE_LENGTH


def test_a_refused_approval_logs_no_approval(installation, superadmin, log_messages):
    data = build_package()
    package = installation.upload(upload_file(data), len(data), superadmin)

    with pytest.raises(UntrustedNotAcknowledgedError):
        installation.approve(package.pk, superadmin, untrusted_acknowledged=False)

    assert _lines(log_messages, "PluginInstallationService.approve") == []


def test_a_rejection_logs_the_package_taken_before_its_row_was_deleted(installation, superadmin, log_messages):
    data = build_package()
    package = installation.upload(upload_file(data), len(data), superadmin)

    installation.reject(package.pk, superadmin)

    [action, digest] = _lines(log_messages, "PluginInstallationService.reject")
    assert action == (
        f"PluginInstallationService.reject {_actor(superadmin)} package={package.pk} plugin=weather "
        "version=0.1.0 plugin_removed=True"
    )
    assert digest == f"PluginInstallationService.reject package={package.pk} sha256={hashlib.sha256(data).hexdigest()}"


def test_a_grant_logs_the_plugin_and_the_organization(running_plugin, superadmin, acme, log_messages):
    running_plugin()

    grant = PluginGrantService().grant("weather", acme.id, superadmin)

    assert _lines(log_messages, "PluginGrantService.grant") == [
        f"PluginGrantService.grant {_actor(superadmin)} plugin=weather grant={grant.pk} "
        f"org={acme.id} org_name='{acme.name}'"
    ]


@pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")
def test_the_api_logs_the_logged_in_superadmin(superadmin_client, superadmin_user, log_messages):
    review = superadmin_client.post(
        "/api/admin/plugins/packages/", {"file": upload_file(build_package())}, format="multipart"
    ).json()

    superadmin_client.post(f"/api/admin/plugins/packages/{review['id']}/reject/")

    for prefix in ("PluginInstallationService.upload", "PluginInstallationService.reject"):
        assert _actor(superadmin_user) in _lines(log_messages, prefix)[0]


def test_no_log_line_carries_file_contents(installation, superadmin, log_messages, trusts_release_key):
    data = build_package(signed_with=trusts_release_key)
    package = installation.upload(upload_file(data), len(data), superadmin)
    installation.approve(package.pk, superadmin, untrusted_acknowledged=False)

    plugin_lines = [line for line in log_messages if line.startswith("PluginInstallationService.")]
    assert plugin_lines
    for forbidden in ("<!doctype", "<svg", "untrusted comment", "manifest_version"):
        assert not any(forbidden in line for line in plugin_lines), forbidden


# ---- plugin login: ids only, never a code, verifier, token, cookie or state ----


def _login_lines(messages):
    return [message for message in messages if message.startswith(("plugins.login.", "plugins.origin_refused"))]


def _assert_no_secret(lines, *secrets):
    for line in lines:
        assert len(line) <= MAX_MESSAGE_LENGTH
        for secret in secrets:
            assert secret not in line


@pytest.mark.usefixtures("login_platform")
def test_a_token_issued_is_logged_with_ids_only(loginable_weather, grant_to, acme, member_only, log_messages):
    grant_to(loginable_weather, acme)
    client = APIClient()
    verifier, challenge = pkce_pair()
    cookie = session_cookie(member_only)
    _, result = redirect_parts(authorize(client, cookie=cookie, challenge=challenge))
    code = result["code"]

    response = exchange(client, code, verifier)

    token = response.json()["access_token"]
    jti = jwt.decode(token, options={"verify_signature": False})["jti"]
    assert _lines(log_messages, "plugins.login.token_issued") == [
        f"plugins.login.token_issued user_id={member_only.pk} org_id={acme.pk} plugin=weather jti={jti}"
    ]
    _assert_no_secret(_login_lines(log_messages), code, verifier, challenge, token, STATE, cookie.partition("=")[2])


@pytest.mark.usefixtures("login_platform")
def test_refused_logins_are_logged_with_their_reason(loginable_weather, grant_to, acme, beta, member_only, make_member, role_member, log_messages):
    grant = grant_to(loginable_weather, acme)
    client = APIClient()
    stranger = make_member(beta, role_member, "stranger-audit@example.com")
    authorize(client, cookie=session_cookie(stranger))
    authorize(client, cookie=session_cookie(member_only), org=str(beta.pk))
    verifier, challenge = pkce_pair()
    code = code_for(client, member_only, challenge=challenge)
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.SUSPENDED)
    exchange(client, code, verifier)

    assert _lines(log_messages, "plugins.login.access_denied") == [
        f"plugins.login.access_denied user_id={stranger.pk} plugin=weather reason=no_eligible_org",
        f"plugins.login.access_denied user_id={member_only.pk} plugin=weather reason=org_not_eligible",
        f"plugins.login.access_denied user_id={member_only.pk} plugin=weather reason=not_eligible",
    ]
    _assert_no_secret(_login_lines(log_messages), code, verifier, challenge, STATE)


@pytest.mark.usefixtures("login_platform")
def test_an_origin_refusal_is_logged_without_the_request_s_credentials(member_only, log_messages):
    cookie = session_cookie(member_only)
    client = APIClient()
    client.credentials(HTTP_ORIGIN=WEATHER_ORIGIN, HTTP_AUTHORIZATION="Bearer bearer-secret")

    client.post(f"/api/auth/logout/?state={STATE}", HTTP_COOKIE=cookie)

    assert _lines(log_messages, "plugins.origin_refused") == [
        f"plugins.origin_refused origin='{WEATHER_ORIGIN}' method='POST' path='/api/auth/logout/'"
    ]
    _assert_no_secret(_login_lines(log_messages), cookie.partition("=")[2], "bearer-secret", STATE)
