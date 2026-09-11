"""Task 7: NgrokConfigInlineSerializer's auth_token_secret_id is gated behind secrets:USE, resolving the current value through the declared parent_attribute rather than the field name."""

import pytest
from rest_framework.test import APIClient

from tables.models import Organization
from tables.models.rbac_models import OrganizationUser, Role, RolePermission
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.models.webhook_models import (
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
)
from tables.services.secrets import secret_service


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
        email="ngrok_nouse@example.com",
        secrets_bitmask=int(Permission.READ),
    )


@pytest.fixture
def use_client(db, django_user_model, default_org):
    return _client_with(
        org=default_org,
        django_user_model=django_user_model,
        email="ngrok_use@example.com",
        secrets_bitmask=int(Permission.READ | Permission.USE),
    )


@pytest.fixture
def secret(default_org):
    return secret_service.create(
        text="sk-ngrok-a", org=default_org, name="NGROK_SECRET_A"
    )


@pytest.fixture
def other_secret(default_org):
    return secret_service.create(
        text="sk-ngrok-b", org=default_org, name="NGROK_SECRET_B"
    )


@pytest.fixture
def trigger(default_org, secret) -> WebhookTrigger:
    trigger = WebhookTrigger.objects.create(
        path="ngrok-inline-trigger",
        provider_type=ProviderType.NGROK,
        org=default_org,
    )
    NgrokWebhookConfig.objects.create(
        trigger=trigger, name="tunnel", auth_token_secret=secret, region="eu"
    )
    return trigger


@pytest.mark.django_db
class TestNgrokInlineIsGated:
    def test_editing_the_path_while_resending_the_token_is_accepted(
        self, no_use_client, trigger, secret
    ):
        """The test that catches a wrong parent_attribute — derive it and this 400s."""
        response = no_use_client.patch(
            f"/api/webhook-triggers/{trigger.id}/",
            {
                "path": "/moved",
                "provider_type": "ngrok",
                "ngrok_config": {
                    "name": "tunnel",
                    "auth_token_secret_id": secret.id,
                    "region": "eu",
                },
            },
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_changing_the_token_without_use_is_rejected(
        self, no_use_client, trigger, other_secret
    ):
        response = no_use_client.patch(
            f"/api/webhook-triggers/{trigger.id}/",
            {
                "path": "/hook",
                "provider_type": "ngrok",
                "ngrok_config": {
                    "name": "tunnel",
                    "auth_token_secret_id": other_secret.id,
                    "region": "eu",
                },
            },
            format="json",
        )

        assert response.status_code == 400
        assert "auth_token_secret_id" in str(response.json())

    def test_use_holder_can_change_the_token(self, use_client, trigger, other_secret):
        response = use_client.patch(
            f"/api/webhook-triggers/{trigger.id}/",
            {
                "path": "/hook",
                "provider_type": "ngrok",
                "ngrok_config": {
                    "name": "tunnel",
                    "auth_token_secret_id": other_secret.id,
                    "region": "eu",
                },
            },
            format="json",
        )

        assert response.status_code == 200, response.json()
        config = NgrokWebhookConfig.objects.get(trigger=trigger)
        assert config.auth_token_secret_id == other_secret.id
