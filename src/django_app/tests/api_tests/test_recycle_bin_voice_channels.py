"""Voice channels: bin with their Twilio settings, routing skips binned ones, a taken number is dropped on restore."""

import pytest
from tables.models import RealtimeChannel, TwilioChannel
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

CHANNELS_URL = "/api/realtime-channels/"


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _channel(org, name="Support line", phone="+15550001111"):
    channel = RealtimeChannel.objects.create(org=org, name=name)
    TwilioChannel.objects.create(channel=channel, account_sid="AC1", phone_number=phone)
    return channel


def _details(entry: dict) -> dict:
    return {detail["label"]: detail for detail in entry["details"]}


def test_the_twilio_settings_go_to_the_bin_and_come_back_with_the_channel(admin_client, acme):
    channel = _channel(acme)

    assert admin_client.delete(f"{CHANNELS_URL}{channel.pk}/").status_code == 204
    assert not TwilioChannel.objects.filter(pk=channel.pk).exists()
    assert TwilioChannel.all_objects.filter(pk=channel.pk, active=False).exists()

    entry = admin_client.get(f"{CHANNELS_URL}recycle-bin/").json()[0]
    assert _details(entry)["Phone number"]["value"] == "+15550001111"
    # It has no agent, so the bin says it won't answer calls; its number is still free.
    warning = _details(entry)["Comes back"]
    assert warning["format"] == "notice"
    assert "Without an agent" in warning["value"]
    assert "phone number" not in warning["value"]

    assert admin_client.post(f"{CHANNELS_URL}{channel.pk}/restore/").status_code == 200
    assert TwilioChannel.objects.get(pk=channel.pk).phone_number == "+15550001111"


def test_a_binned_channel_doesnt_route_calls_and_a_disabled_one_stays_listed(acme):
    binned = _channel(acme)
    disabled = _channel(acme, name="Night line", phone="+15550003333")
    RealtimeChannel.objects.filter(pk=disabled.pk).update(is_enabled=False)

    binned.delete()

    assert not RealtimeChannel.enabled_objects.filter(token=binned.token).exists()
    assert not RealtimeChannel.objects.filter(pk=binned.pk).exists()
    assert RealtimeChannel.objects.filter(pk=disabled.pk).exists()


def test_a_taken_phone_number_is_dropped_on_restore_and_the_bin_warns_first(admin_client, acme):
    channel = _channel(acme)
    admin_client.delete(f"{CHANNELS_URL}{channel.pk}/")
    _channel(acme, name="New line", phone="+15550001111")

    entry = admin_client.get(f"{CHANNELS_URL}recycle-bin/").json()[0]
    warning = _details(entry)["Comes back"]
    assert warning["format"] == "notice"
    assert "+15550001111" in warning["value"]

    assert admin_client.post(f"{CHANNELS_URL}{channel.pk}/restore/").status_code == 200
    assert TwilioChannel.objects.get(pk=channel.pk).phone_number is None


def test_a_channel_name_is_never_renamed(admin_client, acme):
    channel = _channel(acme, phone="+15550002222")
    admin_client.delete(f"{CHANNELS_URL}{channel.pk}/")
    RealtimeChannel.objects.create(org=acme, name="Support line")

    restored = admin_client.post(f"{CHANNELS_URL}{channel.pk}/restore/").json()

    assert restored["renamed_from"] is None
    assert restored["name"] == "Support line"
