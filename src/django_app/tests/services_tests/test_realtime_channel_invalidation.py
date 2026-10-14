"""Coverage for the `post_save`/`post_delete` signal receivers on
`RealtimeChannel` (`realtime_channel_post_save_handler` /
`realtime_channel_post_delete_handler` in `webhook_signals.py`) --
publishing to `realtime_channels:invalidate` so `realtime`'s per-channel
config cache (`_channel_cache`, TTL 60s) doesn't keep serving a channel
Django just changed (e.g. `is_enabled` toggled off) or removed entirely."""

from unittest import mock

import pytest

from rbac.models import Organization
from tables.models.webhook_models import RealtimeChannel


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org RealtimeChannelInvalidation")


def _create(org):
    return RealtimeChannel.objects.create(name="Voice line", org=org)


def _disable(channel):
    channel.is_enabled = False
    channel.save()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "change",
    [lambda org, channel: _create(org), lambda org, channel: _disable(channel), lambda org, channel: channel.delete()],
    ids=["create", "update", "delete"],
)
def test_every_channel_change_tells_realtime_to_drop_its_cached_config(
    org, django_capture_on_commit_callbacks, change
):
    channel = _create(org)
    token = channel.token
    with mock.patch("tables.signals.webhook_signals.RedisService") as redis_service, \
            django_capture_on_commit_callbacks(execute=True):
        changed = change(org, channel)

    expected_token = changed.token if isinstance(changed, RealtimeChannel) else token
    redis_service.return_value.publish_channel_invalidation.assert_called_once_with(expected_token)
