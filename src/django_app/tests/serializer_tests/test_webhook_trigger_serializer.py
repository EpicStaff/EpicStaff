"""`WebhookTriggerSerializer` (`tables/serializers/model_serializers/
webhook_serializers.py`) must reject a `path` that some *other* org already
registered -- regardless of `provider_type` -- with a clean validation
error, not a raw `IntegrityError` bubbling up from the DB's global
uniqueness constraint on `WebhookTrigger.path` (see the `unique=True` on
that field).
"""

import pytest
from rest_framework import serializers

from rbac.models import Organization
from tables.models.webhook_models import ProviderType, WebhookTrigger
from tables.serializers.model_serializers.webhook_serializers import (
    WebhookTriggerSerializer,
)


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Other org for serializer test")


@pytest.mark.django_db
class TestWebhookTriggerSerializerPathUniqueness:
    def test_rejects_path_already_claimed_by_another_org(self, default_org, other_org):
        WebhookTrigger.objects.create(
            path="claimed-elsewhere",
            provider_type=ProviderType.NGROK,
            org=other_org,
        )

        serializer = WebhookTriggerSerializer(
            data={"path": "claimed-elsewhere", "provider_type": ProviderType.NGROK}
        )

        with pytest.raises(serializers.ValidationError):
            serializer.is_valid(raise_exception=True)

        # No leak of which org owns the existing registration.
        assert "other" not in str(serializer.errors).lower()
        assert str(other_org.id) not in str(serializer.errors)

    def test_accepts_fresh_unclaimed_path(self, default_org):
        serializer = WebhookTriggerSerializer(
            data={"path": "brand-new-path", "provider_type": ProviderType.NGROK}
        )

        assert serializer.is_valid(), serializer.errors

    def test_update_excludes_its_own_row_from_the_collision_check(
        self, default_org
    ):
        trigger = WebhookTrigger.objects.create(
            path="mine", provider_type=ProviderType.NGROK, org=default_org
        )

        serializer = WebhookTriggerSerializer(
            instance=trigger,
            data={"path": "mine", "provider_type": ProviderType.NGROK},
        )

        assert serializer.is_valid(), serializer.errors

    def test_update_still_rejects_collision_with_a_different_row(
        self, default_org, other_org
    ):
        WebhookTrigger.objects.create(
            path="already-taken", provider_type=ProviderType.NGROK, org=other_org
        )
        trigger = WebhookTrigger.objects.create(
            path="mine-2", provider_type=ProviderType.NGROK, org=default_org
        )

        serializer = WebhookTriggerSerializer(
            instance=trigger,
            data={"path": "already-taken", "provider_type": ProviderType.NGROK},
        )

        with pytest.raises(serializers.ValidationError):
            serializer.is_valid(raise_exception=True)

    def test_rejects_path_claimed_by_a_different_provider_type(
        self, default_org, other_org
    ):
        """Behavior change: a shared path used to be legal as long as the
        two rows had different `provider_type` values. Uniqueness is now on
        `path` alone, so this must be rejected too."""
        WebhookTrigger.objects.create(
            path="claimed-elsewhere-2",
            provider_type=ProviderType.NGROK,
            org=other_org,
        )

        serializer = WebhookTriggerSerializer(
            data={
                "path": "claimed-elsewhere-2",
                "provider_type": ProviderType.LOCALHOST,
            }
        )

        with pytest.raises(serializers.ValidationError):
            serializer.is_valid(raise_exception=True)
