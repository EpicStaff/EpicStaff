"""Coverage for `RealtimeChannel.save()` / `RealtimeChannel.delete()` --
publishing to `realtime_channels:invalidate` so `realtime`'s per-channel
config cache (`_channel_cache`, TTL 60s) doesn't keep serving a channel
Django just changed (e.g. `is_enabled` toggled off) or removed entirely."""

from unittest import mock

import pytest

from tables.models.rbac_models import Organization
from tables.models.webhook_models import RealtimeChannel


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org RealtimeChannelInvalidation")


@pytest.mark.django_db
class TestRealtimeChannelInvalidation:
    def test_create_publishes_invalidation_with_new_channels_token(
        self, org, django_capture_on_commit_callbacks
    ):
        with mock.patch(
            "tables.services.redis_service.RedisService"
        ) as mock_redis_service_cls, django_capture_on_commit_callbacks(execute=True):
            channel = RealtimeChannel.objects.create(name="Voice line", org=org)

        mock_redis_service_cls.assert_called_once_with()
        mock_redis_service_cls.return_value.publish_channel_invalidation.assert_called_once_with(
            channel.token
        )

    def test_update_publishes_invalidation_with_same_token(
        self, org, django_capture_on_commit_callbacks
    ):
        channel = RealtimeChannel.objects.create(name="Voice line", org=org)

        with mock.patch(
            "tables.services.redis_service.RedisService"
        ) as mock_redis_service_cls, django_capture_on_commit_callbacks(execute=True):
            channel.is_enabled = False
            channel.save()

        mock_redis_service_cls.return_value.publish_channel_invalidation.assert_called_once_with(
            channel.token
        )

    def test_delete_publishes_invalidation_with_deleted_channels_token(
        self, org, django_capture_on_commit_callbacks
    ):
        channel = RealtimeChannel.objects.create(name="Voice line", org=org)
        token = channel.token

        with mock.patch(
            "tables.services.redis_service.RedisService"
        ) as mock_redis_service_cls, django_capture_on_commit_callbacks(execute=True):
            channel.delete()

        mock_redis_service_cls.return_value.publish_channel_invalidation.assert_called_once_with(
            token
        )
