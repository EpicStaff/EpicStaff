"""Coverage for the `VoiceSettings` Twilio-credential secret-FK migration
(EST-3207 follow-up): `twilio_account_sid`/`twilio_auth_token` moved from
plaintext CharFields to `Secret` FKs (`twilio_account_sid_secret` /
`twilio_auth_token_secret`).

Two trust boundaries on the same `/api/voice-settings/` endpoint:
- A JWT-authenticated superadmin session only ever sees/writes the
  `*_secret_id` fields (`VoiceSettingsSerializer`).
- A `key_type=SYSTEM` API-key caller (the `realtime` service's legacy
  `POST /voice` webhook, which needs the real `twilio_auth_token` to
  validate `X-Twilio-Signature`) gets the resolved plaintext values too
  (`VoiceSettingsInternalSerializer`) — mirrors
  `RealtimeChannelInternalSerializer` / EST-3633.
"""

import pytest
from django.urls import reverse

from tables.models.webhook_models import VoiceSettings
from tables.services.secrets import secret_service


@pytest.fixture
def voice_settings_secrets(default_org):
    # `VoiceSettings` itself has no owning org, but `Secret.org_id` is
    # DB-level NOT NULL (0208_secret.py) — any real org works here since a
    # superadmin can point `*_secret_id` at a Secret from any org.
    account_sid_secret = secret_service.create(
        text="AC_test_sid",
        org=default_org,
        name="voicesettings-twilio-account-sid-test",
    )
    auth_token_secret = secret_service.create(
        text="test-auth-token-value",
        org=default_org,
        name="voicesettings-twilio-auth-token-test",
    )
    VoiceSettings.objects.update_or_create(
        pk=1,
        defaults={
            "twilio_account_sid_secret": account_sid_secret,
            "twilio_auth_token_secret": auth_token_secret,
        },
    )
    return account_sid_secret, auth_token_secret


@pytest.mark.django_db
def test_superadmin_get_returns_secret_ids_not_plaintext(
    superadmin_client, voice_settings_secrets
):
    account_sid_secret, auth_token_secret = voice_settings_secrets

    response = superadmin_client.get(reverse("voice-settings"))

    assert response.status_code == 200
    body = response.json()
    assert body["twilio_account_sid_secret_id"] == account_sid_secret.pk
    assert body["twilio_auth_token_secret_id"] == auth_token_secret.pk
    assert "twilio_account_sid" not in body
    assert "twilio_auth_token" not in body


@pytest.mark.django_db
def test_system_api_key_get_returns_resolved_plaintext(
    api_client, env_api_key, voice_settings_secrets
):
    raw_key, _key = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key)

    response = api_client.get(reverse("voice-settings"))

    assert response.status_code == 200
    body = response.json()
    assert body["twilio_account_sid"] == "AC_test_sid"
    assert body["twilio_auth_token"] == "test-auth-token-value"
    # Still exposes the ids too (superset of the superadmin shape).
    assert body["twilio_account_sid_secret_id"] is not None
    assert body["twilio_auth_token_secret_id"] is not None


@pytest.mark.django_db
def test_user_scoped_api_key_does_not_get_resolved_plaintext(
    api_client, user_api_key, voice_settings_secrets
):
    """A self-issued USER key must not reach the internal/resolved shape —
    only a `key_type=SYSTEM` key does. `IsSuperadmin` still lets it through
    (regular_user is an Org Admin, not a superadmin) — actually a USER key
    is rejected earlier by `IsSuperadmin` unless its owner is a superadmin;
    this asserts the response is denied rather than silently downgraded."""
    raw_key, _key = user_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key)

    response = api_client.get(reverse("voice-settings"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_superadmin_patch_sets_secret_fk(superadmin_client, default_org):
    secret = secret_service.create(
        text="AC_new_sid", org=default_org, name="voicesettings-patch-test-sid"
    )
    VoiceSettings.objects.get_or_create(pk=1)

    response = superadmin_client.patch(
        reverse("voice-settings"),
        {"twilio_account_sid_secret_id": secret.pk},
        format="json",
    )

    assert response.status_code == 200, response.json()
    assert response.json()["twilio_account_sid_secret_id"] == secret.pk
    vs = VoiceSettings.load()
    assert vs.twilio_account_sid_secret_id == secret.pk
