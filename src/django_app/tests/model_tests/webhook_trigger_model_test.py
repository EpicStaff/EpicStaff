"""Regression coverage for two review findings on `WebhookTrigger`
(`tables/models/webhook_models.py`):

1. `get_active_config()` must return `None` — not raise `DoesNotExist` — when
   `provider_type` is set but the corresponding child config row (ngrok /
   localhost) hasn't been created yet. This is reachable any time
   `provider_type` is stamped before the child row exists, e.g. mid-way
   through the configure-webhook flow.

2. `unique_together` on `WebhookTrigger` now includes `org`, so two different
   orgs can use the same `path` + `provider_type` combination without
   colliding (previously a global `(path, provider_type)` unique constraint
   caused cross-tenant collisions and acted as a cross-org existence oracle).
"""

import pytest
from django.db import IntegrityError, transaction

from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
)


@pytest.fixture
def other_org(db):
    from tables.models.rbac_models import Organization

    return Organization.objects.create(name="Other Organization For Webhook Test")


@pytest.mark.django_db
class TestGetActiveConfigMissingChildRow:
    def test_returns_none_when_ngrok_provider_type_set_without_child_row(
        self, default_org
    ):
        trigger = WebhookTrigger.objects.create(
            path="pending-ngrok", provider_type=ProviderType.NGROK, org=default_org
        )

        assert trigger.get_active_config() is None

    def test_returns_none_when_localhost_provider_type_set_without_child_row(
        self, default_org
    ):
        trigger = WebhookTrigger.objects.create(
            path="pending-localhost",
            provider_type=ProviderType.LOCALHOST,
            org=default_org,
        )

        assert trigger.get_active_config() is None

    def test_returns_config_when_ngrok_child_row_exists(self, default_org):
        trigger = WebhookTrigger.objects.create(
            path="ready-ngrok", provider_type=ProviderType.NGROK, org=default_org
        )
        config = NgrokWebhookConfig.objects.create(
            name="cfg", auth_token="tok", trigger=trigger
        )

        assert trigger.get_active_config() == config

    def test_returns_config_when_localhost_child_row_exists(self, default_org):
        trigger = WebhookTrigger.objects.create(
            path="ready-localhost",
            provider_type=ProviderType.LOCALHOST,
            org=default_org,
        )
        config = LocalhostWebhookConfig.objects.create(name="cfg", trigger=trigger)

        assert trigger.get_active_config() == config

    def test_returns_none_when_provider_type_is_unset(self, default_org):
        trigger = WebhookTrigger.objects.create(
            path="no-provider", provider_type=None, org=default_org
        )

        assert trigger.get_active_config() is None


@pytest.mark.django_db
class TestWebhookTriggerOrgScopedUniqueConstraint:
    def test_two_orgs_can_share_same_path_and_provider_type(
        self, default_org, other_org
    ):
        WebhookTrigger.objects.create(
            path="shared-path", provider_type=ProviderType.NGROK, org=default_org
        )

        # Must NOT raise — same path+provider_type is allowed across orgs.
        WebhookTrigger.objects.create(
            path="shared-path", provider_type=ProviderType.NGROK, org=other_org
        )

        assert WebhookTrigger.objects.filter(path="shared-path").count() == 2

    def test_same_org_same_path_and_provider_type_still_rejected(self, default_org):
        WebhookTrigger.objects.create(
            path="dup-path", provider_type=ProviderType.NGROK, org=default_org
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                WebhookTrigger.objects.create(
                    path="dup-path",
                    provider_type=ProviderType.NGROK,
                    org=default_org,
                )
