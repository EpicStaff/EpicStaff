"""Regression coverage for two review findings on `WebhookTrigger`
(`tables/models/webhook_models.py`):

1. `get_active_config()` must return `None` — not raise `DoesNotExist` — when
   `provider_type` is set but the corresponding child config row (ngrok /
   localhost) hasn't been created yet. This is reachable any time
   `provider_type` is stamped before the child row exists, e.g. mid-way
   through the configure-webhook flow.

2. `WebhookTrigger.path` is globally unique on its own (`unique=True`) --
   not merely unique within an org, and not scoped by `provider_type`. A
   colliding `path` between two different orgs -- or even between two
   different `provider_type` values -- must raise `IntegrityError` at the
   DB layer: the downstream `webhook` FastAPI service resolves inbound
   requests by bare path with no org or provider discriminant, so an
   org-scoped-only (or provider-scoped) constraint would let one org's
   import silently break a sibling org's webhook deliveries.
"""

import pytest
from django.db import IntegrityError, transaction

from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
)
from tables.services.secrets import secret_service


@pytest.fixture
def other_org(db):
    from rbac.models import Organization

    return Organization.objects.create(name="Other Organization For Webhook Test")


@pytest.mark.parametrize(
    ("provider_type", "make_config"),
    [
        (ProviderType.NGROK, None),
        (ProviderType.LOCALHOST, None),
        (None, None),
        (
            ProviderType.NGROK,
            lambda trigger, org: NgrokWebhookConfig.objects.create(
                name="cfg", auth_token_secret=secret_service.create(text="tok", org=org, name="cfg-secret"), trigger=trigger
            ),
        ),
        (ProviderType.LOCALHOST, lambda trigger, org: LocalhostWebhookConfig.objects.create(name="cfg", trigger=trigger)),
    ],
    ids=["ngrok-without-config-yet", "localhost-without-config-yet", "no-provider", "ngrok-config", "localhost-config"],
)
@pytest.mark.django_db
def test_active_config_is_the_providers_config_or_none_until_it_exists(default_org, provider_type, make_config):
    """Reachable mid-way through the configure-webhook flow: provider stamped, config not yet created."""
    trigger = WebhookTrigger.objects.create(path="hook", provider_type=provider_type, org=default_org)
    config = make_config(trigger, default_org) if make_config else None

    assert trigger.get_active_config() == config


@pytest.mark.django_db
class TestWebhookTriggerGlobalUniqueConstraint:
    def test_two_orgs_sharing_same_path_and_provider_type_is_rejected(
        self, default_org, other_org
    ):
        """The bug this constraint fixes: without a globally unique `path`,
        a Member of one org could register a path already claimed by a
        sibling org and silently break that org's webhook deliveries (the
        `webhook` FastAPI service resolves by bare path, with no org
        discriminant)."""
        WebhookTrigger.objects.create(
            path="shared-path", provider_type=ProviderType.NGROK, org=default_org
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                WebhookTrigger.objects.create(
                    path="shared-path",
                    provider_type=ProviderType.NGROK,
                    org=other_org,
                )

        assert WebhookTrigger.objects.filter(path="shared-path").count() == 1

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

    def test_same_path_different_provider_type_is_now_also_rejected(
        self, default_org, other_org
    ):
        """Behavior change: uniqueness is now on `path` alone, so a shared
        path is no longer legal even when the two rows use different
        `provider_type` values (it used to be legal under the old
        `(path, provider_type)` constraint)."""
        WebhookTrigger.objects.create(
            path="cross-provider-path",
            provider_type=ProviderType.NGROK,
            org=default_org,
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                WebhookTrigger.objects.create(
                    path="cross-provider-path",
                    provider_type=ProviderType.LOCALHOST,
                    org=other_org,
                )

        assert (
            WebhookTrigger.objects.filter(path="cross-provider-path").count() == 1
        )
