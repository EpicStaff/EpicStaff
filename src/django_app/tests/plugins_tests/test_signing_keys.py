"""Context-signing keys: created at start-up only, rotation, JWKS retention, the JWKS endpoint."""

import base64
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from epicstaff_plugin.contracts.gateway_context import Jwks
from plugins.exceptions import SigningKeyMissingError
from plugins.identity.signing_keys import PluginSigningKeyService, cached_signing_key
from plugins.models import PluginSigningKey

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled")]

JWKS_URL = "/api/plugin-public/jwks/"


@pytest.fixture
def first_key(db):
    return PluginSigningKeyService().ensure_key()


def test_ensuring_a_key_creates_the_first_one_once():
    service = PluginSigningKeyService()

    created = service.ensure_key()
    again = service.ensure_key()

    stored = PluginSigningKey.objects.get()
    assert created.kid == again.kid == stored.kid == service.active_key().kid
    assert len(stored.kid) == 16 and int(stored.kid, 16) >= 0
    assert stored.retired_at is None


def test_reading_without_a_key_never_creates_one():
    service = PluginSigningKeyService()

    with pytest.raises(SigningKeyMissingError):
        service.active_key()
    with pytest.raises(SigningKeyMissingError):
        service.jwks()

    assert not PluginSigningKey.objects.exists()


def test_the_jwks_endpoint_without_a_key_is_empty_and_not_cached(anonymous_client):
    response = anonymous_client.get(JWKS_URL)

    assert response.json() == {"keys": []}
    assert response["Cache-Control"] == "no-store"
    assert not PluginSigningKey.objects.exists()


def test_the_private_key_is_stored_encrypted(first_key):
    key = PluginSigningKeyService().active_key()
    seed = key.private_key.private_bytes_raw()

    stored = PluginSigningKey.objects.get()

    assert base64.b64encode(seed).decode() not in stored.private_key_encrypted
    assert len(base64.urlsafe_b64decode(stored.public_key + "=")) == 32


def test_the_same_key_keeps_signing_until_a_rotation(first_key):
    service = PluginSigningKeyService()

    assert service.active_key().kid == service.active_key().kid
    assert PluginSigningKey.objects.count() == 1


def test_a_rotation_retires_the_old_key_and_signs_with_the_new_one(first_key):
    service = PluginSigningKeyService()
    old = service.active_key().kid

    new = service.rotate()

    assert service.active_key().kid == new.kid != old
    assert PluginSigningKey.objects.get(kid=old).retired_at is not None


def test_a_rotation_reaches_this_process_s_cached_key_at_once(first_key):
    before = cached_signing_key.get().kid

    rotated = PluginSigningKeyService().rotate()

    assert cached_signing_key.get().kid == rotated.kid != before


def test_the_jwks_keeps_a_retired_key_for_24_hours(first_key):
    service = PluginSigningKeyService()
    old = service.active_key().kid
    new = service.rotate().kid

    assert [key.kid for key in service.jwks().keys] == [new, old]
    PluginSigningKey.objects.filter(kid=old).update(retired_at=timezone.now() - timedelta(hours=23, minutes=59))
    assert [key.kid for key in service.jwks().keys] == [new, old]
    PluginSigningKey.objects.filter(kid=old).update(retired_at=timezone.now() - timedelta(hours=24, seconds=1))
    assert [key.kid for key in service.jwks().keys] == [new]


def test_the_jwks_endpoint_is_public_and_cacheable(anonymous_client, first_key):
    response = anonymous_client.get(JWKS_URL)

    assert response.status_code == 200
    assert response["Cache-Control"] == "public, max-age=300"
    jwks = Jwks.model_validate(response.json())
    [key] = jwks.keys
    assert (key.kty, key.crv, key.alg, key.use) == ("OKP", "Ed25519", "EdDSA", "sig")
    assert key.kid == PluginSigningKey.objects.get().kid


def test_the_rotate_command_rotates_and_logs(capsys, mocker, first_key):
    old = PluginSigningKeyService().active_key().kid
    info = mocker.patch("plugins.audit.logger.info")

    call_command("rotate_plugin_signing_key")

    new = PluginSigningKey.objects.get(retired_at__isnull=True).kid
    assert new != old
    assert new in capsys.readouterr().out
    assert info.call_args.kwargs == {"kid": new, "retired": old}
