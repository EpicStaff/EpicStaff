"""WebhookTriggerNestedSerializer.auth_secret_id -- the trigger's own kind=webhook auth secret -- is gated behind secrets:USE."""

# Found by the Task 8 coverage test (`test_every_secret_field_is_guarded_or_exempt`),
# which failed against the pre-existing code with exactly this field. Unlike every
# other guarded field, the persisted value is not a direct model attribute --
# `auth_secret_id` has no `source=` override, so its default source
# ("auth_secret_id") does not exist on `WebhookTrigger`; the real value lives at
# `instance.auth.secret`, one hop through the `WebhookTriggerAuth` OneToOne row --
# hence the `get_current_secret_reference` hook on the serializer rather than a
# plain `source=`.

import pytest
from rest_framework.test import APIClient

from tables.models import Organization
from tables.models.rbac_models import OrganizationUser, Role, RolePermission
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.models.webhook_models import (
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
    WebhookTriggerAuth,
    WebhookTriggerAuthKind,
)
from tables.services.secrets import secret_service

#: WebhookTriggerService.AUTH_SECRET_MIN_LENGTH -- the plaintext must clear this.
_LONG_ENOUGH = "x" * 40


def _client_with(
    *, org: Organization, django_user_model, email: str, secrets_bitmask: int
):
    """An APIClient for a user whose custom role holds `secrets_bitmask` on secrets and full CRUD on llm_configs."""
    role = Role.objects.create(name=f"role-{email}", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.SECRETS.value, permissions=secrets_bitmask
    )
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.LLM_CONFIGS.value,
        permissions=int(
            Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
        ),
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def no_use_client(db, django_user_model, default_org):
    return _client_with(
        org=default_org,
        django_user_model=django_user_model,
        email="wtauth_nouse@example.com",
        secrets_bitmask=int(Permission.READ),
    )


@pytest.fixture
def use_client(db, django_user_model, default_org):
    return _client_with(
        org=default_org,
        django_user_model=django_user_model,
        email="wtauth_use@example.com",
        secrets_bitmask=int(Permission.READ | Permission.USE),
    )


@pytest.fixture
def secret(default_org):
    return secret_service.create(
        text=_LONG_ENOUGH, org=default_org, name="WTAUTH_SECRET_A"
    )


@pytest.fixture
def other_secret(default_org):
    return secret_service.create(
        text=_LONG_ENOUGH + "b", org=default_org, name="WTAUTH_SECRET_B"
    )


@pytest.fixture
def trigger(default_org, secret) -> WebhookTrigger:
    # provider_type=ngrok (with its own config row) rather than localhost, purely so
    # `to_representation` (run after every successful PATCH) has something to read at
    # `instance.ngrok` -- this fixture's provider is otherwise unrelated to the
    # `auth_secret_id` field under test, which lives on the trigger's separate `auth`
    # (kind=webhook) row.
    trigger = WebhookTrigger.objects.create(
        path="wtauth-trigger",
        provider_type=ProviderType.NGROK,
        org=default_org,
    )
    NgrokWebhookConfig.objects.create(trigger=trigger, name="tunnel")
    WebhookTriggerAuth.objects.create(
        trigger=trigger, kind=WebhookTriggerAuthKind.WEBHOOK, secret=secret
    )
    return trigger


@pytest.mark.django_db
class TestWebhookTriggerAuthSecretIsGated:
    def test_resending_the_same_value_is_accepted(self, no_use_client, trigger, secret):
        response = no_use_client.patch(
            f"/api/webhook-triggers/{trigger.id}/",
            {"auth_secret_id": secret.id},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_changing_the_value_without_use_is_rejected(
        self, no_use_client, trigger, other_secret
    ):
        response = no_use_client.patch(
            f"/api/webhook-triggers/{trigger.id}/",
            {"auth_secret_id": other_secret.id},
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert "auth_secret_id" in response.json()["message"]

    def test_use_holder_can_change_the_value(self, use_client, trigger, other_secret):
        response = use_client.patch(
            f"/api/webhook-triggers/{trigger.id}/",
            {"auth_secret_id": other_secret.id},
            format="json",
        )

        assert response.status_code == 200, response.json()
        trigger.refresh_from_db()
        assert trigger.auth.secret_id == other_secret.id

    def test_editing_an_unrelated_field_while_omitting_it_is_accepted(
        self, no_use_client, trigger
    ):
        """Delta rule: omitting the field entirely must never require the permission."""
        response = no_use_client.patch(
            f"/api/webhook-triggers/{trigger.id}/",
            {},
            format="json",
        )

        assert response.status_code == 200, response.json()


@pytest.fixture
def twilio_secret(default_org):
    return secret_service.create(
        text=_LONG_ENOUGH + "twilio", org=default_org, name="WTAUTH_SECRET_TWILIO"
    )


@pytest.fixture
def twilio_trigger(default_org, twilio_secret) -> WebhookTrigger:
    """A trigger whose auth row is kind=twilio with a secret already attached -- the state a TwilioChannel claiming a trigger produces via its own post_save signal, built here directly by ORM since set_trigger_auth_secret refuses to create it."""
    trigger = WebhookTrigger.objects.create(
        path="wtauth-twilio-trigger",
        provider_type=ProviderType.NGROK,
        org=default_org,
    )
    NgrokWebhookConfig.objects.create(trigger=trigger, name="tunnel")
    WebhookTriggerAuth.objects.create(
        trigger=trigger, kind=WebhookTriggerAuthKind.TWILIO, secret=twilio_secret
    )
    return trigger


@pytest.mark.django_db
class TestAuthKindOmittedSecretIdPreservesExistingSecret:
    """Regression test for the auth_kind-only bypass: omitting auth_secret_id must never move the persisted reference."""

    def test_resending_only_auth_kind_without_use_does_not_clear_the_secret(
        self, no_use_client, trigger, secret
    ):
        response = no_use_client.patch(
            f"/api/webhook-triggers/{trigger.id}/",
            {"auth_kind": WebhookTriggerAuthKind.WEBHOOK},
            format="json",
        )

        assert response.status_code == 200, response.json()
        trigger.refresh_from_db()
        assert trigger.auth.secret_id == secret.id

    def test_resending_only_auth_kind_with_use_also_preserves_the_secret(
        self, use_client, trigger, secret
    ):
        response = use_client.patch(
            f"/api/webhook-triggers/{trigger.id}/",
            {"auth_kind": WebhookTriggerAuthKind.WEBHOOK},
            format="json",
        )

        assert response.status_code == 200, response.json()
        trigger.refresh_from_db()
        assert trigger.auth.secret_id == secret.id

    def test_explicit_null_secret_id_without_use_is_still_rejected(
        self, no_use_client, trigger, secret
    ):
        response = no_use_client.patch(
            f"/api/webhook-triggers/{trigger.id}/",
            {"auth_secret_id": None},
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert "auth_secret_id" in response.json()["message"]
        trigger.refresh_from_db()
        assert trigger.auth.secret_id == secret.id

    def test_explicit_null_secret_id_with_use_still_removes_the_secret(
        self, use_client, trigger
    ):
        response = use_client.patch(
            f"/api/webhook-triggers/{trigger.id}/",
            {"auth_secret_id": None},
            format="json",
        )

        assert response.status_code == 200, response.json()
        trigger.refresh_from_db()
        assert trigger.auth.secret_id is None


@pytest.mark.django_db
class TestTwilioBareReservationNowRejectsResendingKindOverAClaimedSecret:
    """Deliberate behavior change: resending auth_kind=twilio no longer silently nulls a claimed secret, it now hits the service's bare-reservation error."""

    def test_resending_twilio_kind_over_an_already_claimed_secret_is_a_400(
        self, no_use_client, twilio_trigger, twilio_secret
    ):
        response = no_use_client.patch(
            f"/api/webhook-triggers/{twilio_trigger.id}/",
            {"auth_kind": WebhookTriggerAuthKind.TWILIO},
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert "bare reservation" in response.json()["message"]
        twilio_trigger.refresh_from_db()
        assert twilio_trigger.auth.secret_id == twilio_secret.id
