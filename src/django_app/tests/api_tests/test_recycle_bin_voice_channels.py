"""Voice channels: bin with their Twilio settings, routing skips binned ones, and a restore
brings the phone number back only when its own Twilio account still has it and no live channel
took it meanwhile. Twilio's HTTP API is the only thing faked here."""

import io
import urllib.error
import urllib.parse
from unittest import mock

import pytest
from tables.models import RealtimeChannel, TwilioChannel
from tables.services.secrets import secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

CHANNELS_URL = "/api/realtime-channels/"
NUMBER = "+15550001111"
ACCOUNT_SID = "AC" + "a" * 32
AUTH_TOKEN = "support-line-token"
NO_AGENT = "Without an agent: it won't answer calls until you pick one in Settings."
NUMBER_IS_CHECKED = f"Its phone number {NUMBER} is checked on restore."
COULD_NOT_VERIFY_ON_RESTORE = (
    "Could not verify the channel's phone number with Twilio. Try the restore again later."
)
RESTORE_THE_AUTH_TOKEN_FIRST = (
    "The channel's Twilio auth token can't be read, so its phone number can't be checked. "
    "If the token is in the recycle bin, restore it first."
)


def _twilio_account(numbers: list[str]):
    """Twilio's `IncomingPhoneNumbers.json` for the one account ACCOUNT_SID / AUTH_TOKEN.

    Any other credentials get Twilio's 401.
    """

    def answer(account_sid, auth_token, url, method="GET", data=None, timeout=None):
        if (account_sid, auth_token) != (ACCOUNT_SID, AUTH_TOKEN):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b"{}"))
        wanted = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["PhoneNumber"][0]
        return {
            "incoming_phone_numbers": [
                {"phone_number": number} for number in numbers if wanted in number
            ]
        }

    return answer


def _twilio(fake_or_error):
    return mock.patch("tables.services.twilio_service._twilio_request", side_effect=fake_or_error)


def _channel(org, name="Support line", phone=NUMBER, account_sid=ACCOUNT_SID, with_token=True):
    channel = RealtimeChannel.objects.create(org=org, name=name)
    secret = (
        secret_service.create(text=AUTH_TOKEN, org=org, name=f"TOKEN_{channel.pk}")
        if with_token
        else None
    )
    TwilioChannel.objects.create(
        channel=channel, account_sid=account_sid, auth_token_secret=secret, phone_number=phone
    )
    return channel


def _details(entry: dict) -> dict:
    return {detail["label"]: detail for detail in entry["details"]}


def _restore(client, channel):
    return client.post(f"{CHANNELS_URL}{channel.pk}/restore/")


def test_the_twilio_settings_go_to_the_bin_and_come_back_with_the_channel(acme_admin_client, acme):
    channel = _channel(acme)

    assert acme_admin_client.delete(f"{CHANNELS_URL}{channel.pk}/").status_code == 204
    assert not TwilioChannel.objects.filter(pk=channel.pk).exists()
    assert TwilioChannel.all_objects.filter(pk=channel.pk, active=False).exists()

    entry = acme_admin_client.get(f"{CHANNELS_URL}recycle-bin/").json()["results"][0]
    assert _details(entry)["Phone number"]["value"] == NUMBER
    warning = _details(entry)["Comes back"]
    assert warning["format"] == "notice"
    assert warning["value"] == f"{NO_AGENT} {NUMBER_IS_CHECKED}"

    with _twilio(_twilio_account([NUMBER])):
        assert _restore(acme_admin_client, channel).status_code == 200
    assert TwilioChannel.objects.get(pk=channel.pk).phone_number == NUMBER


def test_a_binned_channel_doesnt_route_calls_and_a_disabled_one_stays_listed(acme):
    binned = _channel(acme)
    disabled = _channel(acme, name="Night line", phone="+15550003333")
    RealtimeChannel.objects.filter(pk=disabled.pk).update(is_enabled=False)

    binned.delete()

    assert not RealtimeChannel.enabled_objects.filter(token=binned.token).exists()
    assert not RealtimeChannel.objects.filter(pk=binned.pk).exists()
    assert RealtimeChannel.objects.filter(pk=disabled.pk).exists()


def test_the_bin_says_the_same_whether_or_not_another_org_holds_the_number(
    acme_admin_client, acme, beta
):
    """The bin list must not tell whether any org holds a number: same notice either way."""
    channel = _channel(acme)
    acme_admin_client.delete(f"{CHANNELS_URL}{channel.pk}/")

    def notice():
        entry = acme_admin_client.get(f"{CHANNELS_URL}recycle-bin/").json()["results"][0]
        return _details(entry)["Comes back"]

    while_free = notice()
    _channel(beta, name="Beta line", phone=NUMBER)
    while_taken = notice()

    assert while_free == while_taken
    assert while_taken["value"] == f"{NO_AGENT} {NUMBER_IS_CHECKED}"


@pytest.mark.parametrize(
    "account_numbers, holder_org, comes_back_with",
    [
        ([], "beta", None),
        ([NUMBER], "beta", None),
        ([NUMBER], "acme", None),
        ([NUMBER], None, NUMBER),
    ],
    ids=["taken-unproven", "taken-by-another-org-proven", "taken-by-own-org-proven", "free-proven"],
)
def test_a_restore_proves_the_number_first_and_never_takes_it_from_a_live_channel(
    acme_admin_client, acme, beta, account_numbers, holder_org, comes_back_with
):
    channel = _channel(acme)
    acme_admin_client.delete(f"{CHANNELS_URL}{channel.pk}/")
    if holder_org is not None:
        holder = _channel({"acme": acme, "beta": beta}[holder_org], name="Live line")

    with _twilio(_twilio_account(account_numbers)) as twilio:
        response = _restore(acme_admin_client, channel)

    assert response.status_code == 200, response.json()
    assert twilio.called
    assert TwilioChannel.objects.get(pk=channel.pk).phone_number == comes_back_with
    if holder_org is not None:
        assert TwilioChannel.objects.get(pk=holder.pk).phone_number == NUMBER


def test_a_taken_number_still_asks_twilio_so_twilio_down_fails_the_restore(
    acme_admin_client, acme, beta
):
    """Taken or free, the restore answers the same way: the holder is only looked at after Twilio."""
    channel = _channel(acme)
    acme_admin_client.delete(f"{CHANNELS_URL}{channel.pk}/")
    _channel(beta, name="Beta line", phone=NUMBER)

    with _twilio(urllib.error.URLError("Name or service not known")):
        response = _restore(acme_admin_client, channel)

    assert response.status_code == 503
    assert response.json()["message"] == COULD_NOT_VERIFY_ON_RESTORE
    binned = TwilioChannel.all_objects.get(pk=channel.pk)
    assert (binned.active, binned.phone_number) == (False, NUMBER)


def test_a_number_its_twilio_account_no_longer_has_is_dropped_on_restore(acme_admin_client, acme):
    channel = _channel(acme)
    acme_admin_client.delete(f"{CHANNELS_URL}{channel.pk}/")

    with _twilio(_twilio_account(["+15550002222"])):
        response = _restore(acme_admin_client, channel)

    assert response.status_code == 200, response.json()
    restored = TwilioChannel.objects.get(pk=channel.pk)
    assert (restored.phone_number, restored.account_sid) == (None, ACCOUNT_SID)


def _rejected_by_twilio(org):
    return _channel(org, account_sid="AC" + "f" * 32)


def _without_auth_token(org):
    return _channel(org, with_token=False)


def _with_malformed_account_sid(org):
    # Saved before account SIDs were validated.
    return _channel(org, account_sid="AC1")


@pytest.mark.parametrize(
    "make_channel",
    [_rejected_by_twilio, _without_auth_token, _with_malformed_account_sid],
    ids=["credentials-rejected", "no-auth-token", "malformed-account-sid"],
)
def test_a_number_its_credentials_cannot_prove_is_dropped_on_restore(
    acme_admin_client, acme, make_channel
):
    channel = make_channel(acme)
    acme_admin_client.delete(f"{CHANNELS_URL}{channel.pk}/")

    with _twilio(_twilio_account([NUMBER])):
        response = _restore(acme_admin_client, channel)

    assert response.status_code == 200, response.json()
    assert TwilioChannel.objects.get(pk=channel.pk).phone_number is None


def _bin_with_binned_auth_token(client, org, name="Support line"):
    channel = _channel(org, name=name)
    TwilioChannel.objects.get(pk=channel.pk).auth_token_secret.delete()
    client.delete(f"{CHANNELS_URL}{channel.pk}/")
    return channel


def test_a_binned_auth_token_fails_the_restore_and_keeps_the_number(acme_admin_client, acme):
    """The token could still prove the number once restored, so the number isn't dropped."""
    channel = _bin_with_binned_auth_token(acme_admin_client, acme)

    with _twilio(urllib.error.URLError("must not be called")) as twilio:
        response = _restore(acme_admin_client, channel)

    assert response.status_code == 409, response.json()
    assert response.json()["message"] == RESTORE_THE_AUTH_TOKEN_FIRST
    twilio.assert_not_called()
    binned = TwilioChannel.all_objects.get(pk=channel.pk)
    assert (binned.active, binned.phone_number) == (False, NUMBER)


def test_a_binned_auth_token_fails_only_that_item_of_a_bulk_restore(acme_admin_client, acme):
    with_binned_token = _bin_with_binned_auth_token(acme_admin_client, acme)
    without_number = _channel(acme, name="Night line", phone=None)
    acme_admin_client.delete(f"{CHANNELS_URL}{without_number.pk}/")

    response = acme_admin_client.post(
        f"{CHANNELS_URL}recycle-bin/restore/",
        {"ids": [with_binned_token.pk, without_number.pk]},
        format="json",
    )

    assert response.status_code == 200, response.json()
    assert [item["id"] for item in response.json()["restored"]] == [without_number.pk]
    assert response.json()["failed"] == [
        {"id": with_binned_token.pk, "name": "Support line", "message": RESTORE_THE_AUTH_TOKEN_FIRST}
    ]
    assert TwilioChannel.all_objects.get(pk=with_binned_token.pk).phone_number == NUMBER


def test_twilio_down_fails_the_restore_and_keeps_the_channel_in_the_bin(acme_admin_client, acme):
    channel = _channel(acme)
    acme_admin_client.delete(f"{CHANNELS_URL}{channel.pk}/")

    with _twilio(urllib.error.URLError("Name or service not known")):
        response = _restore(acme_admin_client, channel)

    assert response.status_code == 503
    assert response.json()["message"] == COULD_NOT_VERIFY_ON_RESTORE
    binned = TwilioChannel.all_objects.get(pk=channel.pk)
    assert (binned.active, binned.phone_number) == (False, NUMBER)
    assert RealtimeChannel.deleted_objects.filter(pk=channel.pk).exists()


def test_twilio_down_fails_only_that_item_of_a_bulk_restore(acme_admin_client, acme):
    with_number = _channel(acme)
    without_number = _channel(acme, name="Night line", phone=None)
    for channel in (with_number, without_number):
        acme_admin_client.delete(f"{CHANNELS_URL}{channel.pk}/")

    with _twilio(urllib.error.URLError("Name or service not known")):
        response = acme_admin_client.post(
            f"{CHANNELS_URL}recycle-bin/restore/",
            {"ids": [with_number.pk, without_number.pk]},
            format="json",
        )

    assert response.status_code == 200, response.json()
    assert [item["id"] for item in response.json()["restored"]] == [without_number.pk]
    assert response.json()["failed"] == [
        {"id": with_number.pk, "name": "Support line", "message": COULD_NOT_VERIFY_ON_RESTORE}
    ]
    assert TwilioChannel.all_objects.get(pk=with_number.pk).phone_number == NUMBER


def test_a_channel_name_is_never_renamed(acme_admin_client, acme):
    channel = _channel(acme, phone="+15550002222")
    acme_admin_client.delete(f"{CHANNELS_URL}{channel.pk}/")
    RealtimeChannel.objects.create(org=acme, name="Support line")

    with _twilio(_twilio_account(["+15550002222"])):
        restored = _restore(acme_admin_client, channel).json()

    assert restored["renamed_from"] is None
    assert restored["name"] == "Support line"
