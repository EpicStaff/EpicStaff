"""POSTing a Twilio channel that already exists overwrites it, so it needs voice:UPDATE.

The viewset's `create` upserts: when a TwilioChannel row already exists for the
posted `channel`, the request rewrites that row. The RBAC action map only gates the
`create` action with CREATE, so without an explicit check a role holding
voice:CREATE but not voice:UPDATE could rewrite an existing channel.

The order of the three answers is the contract pinned here:
404 (channel of another org) -> 403 (no voice:UPDATE) -> 400 (secret Use check).
"""

import pytest
from rbac.models.enums import Permission, ResourceType
from tables.models.webhook_models import RealtimeChannel, TwilioChannel
from tables.services.secrets import secret_service
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants
from tests.rbac_cross_org_fixtures import beta  # noqa: F401

TWILIO_CHANNELS_URL = "/api/twilio-channels/"


@pytest.fixture
def secret(default_org):
    return secret_service.create(text="twilio-token", org=default_org, name="TWILIO_TOKEN")


@pytest.fixture
def existing_channel(default_org, secret):
    channel = RealtimeChannel.objects.create(name="upsert-twilio-channel", org=default_org)
    return TwilioChannel.objects.create(
        channel=channel, account_sid="AC_original", auth_token_secret=secret
    )


@pytest.fixture
def no_update_client(db, django_user_model, default_org):
    """voice:CREATE|READ and secrets:READ|USE — everything the upsert needs but UPDATE."""
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="twilio-upsert-no-update@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ | Permission.USE),
            ResourceType.VOICE.value: int(Permission.CREATE | Permission.READ),
        },
    )


@pytest.fixture
def no_create_client(db, django_user_model, default_org):
    """voice:UPDATE|READ and secrets:READ|USE — everything the upsert needs but CREATE."""
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="twilio-upsert-no-create@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ | Permission.USE),
            ResourceType.VOICE.value: int(Permission.UPDATE | Permission.READ),
        },
    )


@pytest.fixture
def other_secret(default_org):
    """A second secret, so a write can change the channel's auth-token reference."""
    return secret_service.create(
        text="twilio-token-2", org=default_org, name="TWILIO_TOKEN_SECOND"
    )


@pytest.fixture
def no_update_no_secret_use_client(db, django_user_model, default_org):
    """voice:CREATE|READ and secrets:READ — lacks both voice:UPDATE and secrets:USE."""
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="twilio-upsert-no-update-no-use@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ),
            ResourceType.VOICE.value: int(Permission.CREATE | Permission.READ),
        },
    )


@pytest.fixture
def no_secret_use_client(db, django_user_model, default_org):
    """Full voice CRUD and secrets:READ — lacks only secrets:USE."""
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="twilio-upsert-no-secret-use@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ),
            ResourceType.VOICE.value: FULL_CRUD,
        },
    )


@pytest.fixture
def full_crud_client(db, django_user_model, default_org):
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="twilio-upsert-full-crud@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ | Permission.USE),
            ResourceType.VOICE.value: FULL_CRUD,
        },
    )


def _post(client, channel_pk, secret_pk, account_sid):
    return client.post(
        TWILIO_CHANNELS_URL,
        {
            "channel": channel_pk,
            "account_sid": account_sid,
            "auth_token_secret_id": secret_pk,
        },
        format="json",
    )


@pytest.mark.django_db
def test_upsert_requires_update_permission_denied(no_update_client, existing_channel, secret):
    response = _post(no_update_client, existing_channel.channel_id, secret.pk, "AC_overwritten")

    assert response.status_code == 403, response.json()
    existing_channel.refresh_from_db()
    assert existing_channel.account_sid == "AC_original"


@pytest.mark.django_db
def test_swapping_the_secret_without_use_is_a_400(
    no_secret_use_client, existing_channel, other_secret
):
    # Control for the ordering test below: holding voice:UPDATE, the very same
    # request is answered by the secret Use check.
    response = _post(
        no_secret_use_client, existing_channel.channel_id, other_secret.pk, "AC_overwritten"
    )

    assert response.status_code == 400, response.json()
    existing_channel.refresh_from_db()
    assert existing_channel.account_sid == "AC_original"


@pytest.mark.django_db
def test_upsert_permission_checked_before_secret_validation(
    no_update_no_secret_use_client, existing_channel, other_secret
):
    # The caller fails both checks: no voice:UPDATE (403) and no secrets:USE for the
    # swapped secret (400). A secret check that ran first would answer 400 and so
    # report on the existing row before the caller is known to be allowed to touch it.
    response = _post(
        no_update_no_secret_use_client,
        existing_channel.channel_id,
        other_secret.pk,
        "AC_overwritten",
    )

    assert response.status_code == 403, response.json()
    existing_channel.refresh_from_db()
    assert existing_channel.account_sid == "AC_original"


@pytest.mark.django_db
def test_create_new_channel_not_affected(no_update_client, default_org, secret):
    channel = RealtimeChannel.objects.create(name="brand-new-twilio-channel", org=default_org)

    response = _post(no_update_client, channel.pk, secret.pk, "AC_new")

    assert response.status_code == 201, response.json()
    assert TwilioChannel.objects.get(channel_id=channel.pk).account_sid == "AC_new"


@pytest.mark.django_db
def test_full_crud_can_update_existing_channel(full_crud_client, existing_channel, secret):
    response = _post(full_crud_client, existing_channel.channel_id, secret.pk, "AC_changed")

    assert response.status_code == 200, response.json()
    existing_channel.refresh_from_db()
    assert existing_channel.account_sid == "AC_changed"


@pytest.mark.django_db
def test_cross_org_channel_returns_404_not_403(no_update_client, beta, secret):
    beta_secret = secret_service.create(text="beta-token", org=beta, name="BETA_TWILIO_TOKEN")
    beta_channel = RealtimeChannel.objects.create(name="beta-twilio-channel", org=beta)
    beta_twilio = TwilioChannel.objects.create(
        channel=beta_channel, account_sid="AC_beta", auth_token_secret=beta_secret
    )

    response = _post(no_update_client, beta_channel.pk, secret.pk, "AC_hijacked")

    # 404, not the 403 the missing voice:UPDATE would otherwise give: a 403 would
    # confirm that a Twilio row exists for another org's channel.
    assert response.status_code == 404, response.json()
    beta_twilio.refresh_from_db()
    assert beta_twilio.account_sid == "AC_beta"


@pytest.mark.django_db
def test_upsert_requires_create_permission(no_create_client, existing_channel, secret):
    # 403 comes from the action map gate (CREATE), not the view's explicit UPDATE check.
    response = _post(no_create_client, existing_channel.channel_id, secret.pk, "AC_overwritten")

    assert response.status_code == 403, response.json()
    existing_channel.refresh_from_db()
    assert existing_channel.account_sid == "AC_original"
