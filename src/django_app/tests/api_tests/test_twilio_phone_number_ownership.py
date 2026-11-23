"""A Twilio channel's phone number is saved only once its Twilio account proves it owns it.

A number is unique among live channels across every organization. Before this rule, the
uniqueness check was the first gate, so any org could learn whether another org uses a
number ("already exists" against "created") and could save someone else's number first.
Now a new or changed number is looked up in the channel's own Twilio account: a number the
account doesn't hold gets one answer whether or not another org holds it, and only an owner
ever reaches the uniqueness check. Twilio's HTTP API is the only thing faked here.
"""

import io
import json
import urllib.error
import urllib.parse
from unittest import mock

import pytest
from django.db import IntegrityError
from django.db.models.signals import pre_save
from rbac.models.enums import Permission, ResourceType
from tables.models.webhook_models import RealtimeChannel, TwilioChannel
from tables.services.secrets import secret_service
from tables.services.twilio_service import TwilioService
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants
from tests.error_envelope import details_by_attr, error_text
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

TWILIO_CHANNELS_URL = "/api/twilio-channels/"
ACME_ACCOUNT_SID = "AC" + "a" * 32
ACME_AUTH_TOKEN = "acme-twilio-token"
HOLDER_ACCOUNT_SID = "AC" + "b" * 32
HOLDER_AUTH_TOKEN = "holder-twilio-token"
HELD_NUMBER = "+15550007777"
NOT_HELD_BY_ANYONE = "+15550009999"

NOT_IN_ACCOUNT = "This phone number is not in the given Twilio account."
ALREADY_USED = "This phone number is already used by another voice channel."
COULD_NOT_VERIFY = "Could not verify the phone number with Twilio. Try again later."
CREDENTIALS_REJECTED = "Twilio rejected the account SID or auth token."
NO_AUTH_TOKEN = "No Twilio credentials configured for this channel"
TOKEN_UNAVAILABLE = "The Twilio auth token is unavailable; restore or replace it."
NOT_E164 = "Enter the phone number in E.164 format, for example +15550001234."


class FakeTwilio:
    """Answers `IncomingPhoneNumbers.json` the way Twilio does, for the accounts it is given.

    Twilio matches the `PhoneNumber` filter partially, so a filter can list a longer
    number that merely contains it. Credentials of no account get Twilio's 401; an
    account marked unreachable gets no answer at all, and one given a status gets that
    HTTP error.
    """

    def __init__(self):
        self._numbers_by_credentials: dict[tuple[str, str], list[str]] = {}
        self._unreachable_account_sids: set[str] = set()
        self._status_by_account_sid: dict[str, int] = {}
        self.asked_account_sids: list[str] = []
        self.timeouts: list[float | None] = []

    def with_account(self, account_sid: str, auth_token: str, numbers: list[str]) -> "FakeTwilio":
        self._numbers_by_credentials[(account_sid, auth_token)] = numbers
        return self

    def unreachable_for(self, account_sid: str) -> "FakeTwilio":
        self._unreachable_account_sids.add(account_sid)
        return self

    def answers_with_status(self, account_sid: str, status: int) -> "FakeTwilio":
        self._status_by_account_sid[account_sid] = status
        return self

    def __call__(self, account_sid, auth_token, url, method="GET", data=None, timeout=None):
        self.asked_account_sids.append(account_sid)
        self.timeouts.append(timeout)
        if account_sid in self._unreachable_account_sids:
            raise urllib.error.URLError("Name or service not known")
        if account_sid in self._status_by_account_sid:
            status = self._status_by_account_sid[account_sid]
            raise urllib.error.HTTPError(url, status, "", {}, io.BytesIO(b"{}"))
        numbers = self._numbers_by_credentials.get((account_sid, auth_token))
        if numbers is None:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b"{}"))
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        wanted = query.get("PhoneNumber", [""])[0]
        return {
            "incoming_phone_numbers": [
                {"sid": "PN" + "0" * 32, "phone_number": number, "friendly_name": number}
                for number in numbers
                if wanted in number
            ]
        }


def _acme_account(*numbers: str) -> FakeTwilio:
    return FakeTwilio().with_account(ACME_ACCOUNT_SID, ACME_AUTH_TOKEN, list(numbers))


def _twilio(fake_or_error):
    """Patch Twilio's HTTP boundary with a fake account or an error it raises."""
    return mock.patch("tables.services.twilio_service._twilio_request", side_effect=fake_or_error)


def _field_error(response, expected_field: str) -> str:
    """The message of a 400 the project's exception handler rendered for one field."""
    body = response.json()
    assert response.status_code == 400, body
    details = details_by_attr(body)
    assert list(details) == [expected_field], body
    return details[expected_field][0]


def _phone_number_error(response) -> str:
    return _field_error(response, "phone_number")


@pytest.fixture
def acme_secret(acme):
    return secret_service.create(text=ACME_AUTH_TOKEN, org=acme, name="ACME_TWILIO_TOKEN")


@pytest.fixture
def acme_channel(acme):
    return RealtimeChannel.objects.create(org=acme, name="Acme line")


def _holder(org, account_sid=HOLDER_ACCOUNT_SID) -> TwilioChannel:
    """A live channel of `org` that already holds HELD_NUMBER, saved before numbers were verified."""
    secret = secret_service.create(
        text=HOLDER_AUTH_TOKEN, org=org, name=f"HOLDER_TOKEN_{org.pk}"
    )
    channel = RealtimeChannel.objects.create(org=org, name="Holder line")
    return TwilioChannel.objects.create(
        channel=channel,
        account_sid=account_sid,
        auth_token_secret=secret,
        phone_number=HELD_NUMBER,
    )


@pytest.fixture
def beta_holds_the_number(beta):
    return _holder(beta)


def _holder_owns_it(twilio: FakeTwilio) -> FakeTwilio:
    return twilio.with_account(HOLDER_ACCOUNT_SID, HOLDER_AUTH_TOKEN, [HELD_NUMBER])


def _holder_has_no_numbers(twilio: FakeTwilio) -> FakeTwilio:
    return twilio.with_account(HOLDER_ACCOUNT_SID, HOLDER_AUTH_TOKEN, [])


def _create(client, channel, secret, phone_number, account_sid=ACME_ACCOUNT_SID):
    return client.post(
        TWILIO_CHANNELS_URL,
        {
            "channel": channel.pk,
            "account_sid": account_sid,
            "auth_token_secret_id": secret.pk,
            "phone_number": phone_number,
        },
        format="json",
    )


@pytest.mark.parametrize(
    "caller_auth_token, expected_field, expected_message",
    [
        (ACME_AUTH_TOKEN, "phone_number", NOT_IN_ACCOUNT),
        ("not-the-acme-token", "account_sid", CREDENTIALS_REJECTED),
    ],
    ids=["number-not-in-account", "credentials-rejected"],
)
def test_a_number_another_org_holds_answers_like_a_free_number_the_account_does_not_own(
    acme_admin_client,
    acme,
    acme_channel,
    beta_holds_the_number,
    caller_auth_token,
    expected_field,
    expected_message,
):
    caller_secret = secret_service.create(text=caller_auth_token, org=acme, name="CALLER_TOKEN")
    # The holder doesn't own it either: had it been checked, it would have lost the number.
    twilio = _holder_has_no_numbers(_acme_account("+15550001111"))

    with _twilio(twilio):
        held = _create(acme_admin_client, acme_channel, caller_secret, HELD_NUMBER)
        free = _create(acme_admin_client, acme_channel, caller_secret, NOT_HELD_BY_ANYONE)

    assert held.status_code == free.status_code == 400
    assert held.json() == free.json()
    assert _field_error(held, expected_field) == expected_message
    assert twilio.asked_account_sids == [ACME_ACCOUNT_SID, ACME_ACCOUNT_SID]
    assert not TwilioChannel.objects.filter(channel=acme_channel).exists()
    beta_holds_the_number.refresh_from_db()
    assert beta_holds_the_number.phone_number == HELD_NUMBER


def test_a_number_in_the_channels_twilio_account_is_saved(
    acme_admin_client, acme_channel, acme_secret
):
    account = _acme_account(NOT_HELD_BY_ANYONE)

    with _twilio(account):
        response = _create(acme_admin_client, acme_channel, acme_secret, NOT_HELD_BY_ANYONE)

    assert response.status_code == 201, response.json()
    assert TwilioChannel.objects.get(channel=acme_channel).phone_number == NOT_HELD_BY_ANYONE


def test_a_number_twilio_matches_only_partially_is_not_owned(
    acme_admin_client, acme_channel, acme_secret
):
    # The account holds +155500099991; Twilio's filter for +15550009999 lists it too.
    account = _acme_account("+155500099991")

    with _twilio(account):
        response = _create(acme_admin_client, acme_channel, acme_secret, NOT_HELD_BY_ANYONE)

    assert response.status_code == 400
    assert _phone_number_error(response) == NOT_IN_ACCOUNT


@pytest.mark.parametrize("holder_org", ["beta", "acme"])
def test_a_holder_whose_account_has_the_number_keeps_it_and_the_owner_is_told_it_is_taken(
    acme_admin_client, acme_channel, acme_secret, holder_org, request
):
    holder = _holder(request.getfixturevalue(holder_org))
    twilio = _holder_owns_it(_acme_account(HELD_NUMBER))

    with _twilio(twilio):
        response = _create(acme_admin_client, acme_channel, acme_secret, HELD_NUMBER)

    assert response.status_code == 400
    assert _phone_number_error(response) == ALREADY_USED
    assert twilio.asked_account_sids == [ACME_ACCOUNT_SID, HOLDER_ACCOUNT_SID]
    assert not TwilioChannel.objects.filter(channel=acme_channel).exists()
    holder.refresh_from_db()
    assert holder.phone_number == HELD_NUMBER


@pytest.mark.parametrize(
    "holder_org, method",
    [("beta", "create"), ("acme", "create"), ("beta", "patch")],
)
def test_the_owner_takes_a_number_from_a_holder_whose_account_does_not_have_it(
    acme_admin_client, acme_channel, acme_secret, holder_org, method, request
):
    holder = _holder(request.getfixturevalue(holder_org))
    twilio = _holder_has_no_numbers(_acme_account(HELD_NUMBER))
    if method == "patch":
        TwilioChannel.objects.create(
            channel=acme_channel, account_sid=ACME_ACCOUNT_SID, auth_token_secret=acme_secret
        )

    with _twilio(twilio):
        if method == "create":
            response = _create(acme_admin_client, acme_channel, acme_secret, HELD_NUMBER)
        else:
            response = acme_admin_client.patch(
                f"{TWILIO_CHANNELS_URL}{acme_channel.pk}/",
                {"phone_number": HELD_NUMBER},
                format="json",
            )

    assert response.status_code in (200, 201), response.json()
    assert response.json()["phone_number"] == HELD_NUMBER
    assert TwilioChannel.objects.get(channel=acme_channel).phone_number == HELD_NUMBER
    holder.refresh_from_db()
    assert (holder.phone_number, holder.account_sid, holder.active) == (
        None,
        HOLDER_ACCOUNT_SID,
        True,
    )


def _holder_rejected_by_twilio(org):
    return _holder(org)


def _holder_without_auth_token(org):
    holder = _holder(org)
    TwilioChannel.objects.filter(pk=holder.pk).update(auth_token_secret=None)
    return holder


def _holder_with_binned_auth_token(org):
    holder = _holder(org)
    holder.auth_token_secret.delete()
    return holder


def _holder_with_malformed_account_sid(org):
    # Saved before account SIDs were validated.
    return _holder(org, account_sid="AC1")


@pytest.mark.parametrize(
    "make_holder, holder_is_asked",
    [
        (_holder_rejected_by_twilio, True),
        (_holder_without_auth_token, False),
        (_holder_with_binned_auth_token, False),
        (_holder_with_malformed_account_sid, False),
    ],
    ids=["credentials-rejected", "no-auth-token", "binned-auth-token", "malformed-account-sid"],
)
def test_a_holder_that_cannot_prove_ownership_loses_the_number_to_the_owner(
    acme_admin_client, acme_channel, acme_secret, beta, make_holder, holder_is_asked
):
    holder = make_holder(beta)
    # No account has the holder's credentials: Twilio answers them with a 401.
    twilio = _acme_account(HELD_NUMBER)

    with _twilio(twilio):
        response = _create(acme_admin_client, acme_channel, acme_secret, HELD_NUMBER)

    assert response.status_code == 201, response.json()
    assert (HOLDER_ACCOUNT_SID in twilio.asked_account_sids) is holder_is_asked
    assert TwilioChannel.objects.get(channel=acme_channel).phone_number == HELD_NUMBER
    holder.refresh_from_db()
    assert holder.phone_number is None


def test_twilio_down_while_the_holder_is_checked_is_a_503_and_changes_nothing(
    acme_admin_client, acme_channel, acme_secret, beta_holds_the_number
):
    twilio = _acme_account(HELD_NUMBER).unreachable_for(HOLDER_ACCOUNT_SID)

    with _twilio(twilio):
        response = _create(acme_admin_client, acme_channel, acme_secret, HELD_NUMBER)

    assert response.status_code == 503
    assert error_text(response.json()) == COULD_NOT_VERIFY
    assert not TwilioChannel.objects.filter(channel=acme_channel).exists()
    beta_holds_the_number.refresh_from_db()
    assert beta_holds_the_number.phone_number == HELD_NUMBER


@pytest.mark.parametrize(
    "holder_status, expected_status, holder_keeps_the_number",
    [(401, 201, False), (403, 201, False), (404, 503, True), (400, 503, True)],
)
def test_only_a_definite_credentials_rejection_releases_a_holder(
    acme_admin_client,
    acme_channel,
    acme_secret,
    beta_holds_the_number,
    holder_status,
    expected_status,
    holder_keeps_the_number,
):
    """Any other status is no verdict on the holder, so another org's number stays put."""
    twilio = _acme_account(HELD_NUMBER).answers_with_status(HOLDER_ACCOUNT_SID, holder_status)

    with _twilio(twilio):
        response = _create(acme_admin_client, acme_channel, acme_secret, HELD_NUMBER)

    assert response.status_code == expected_status, response.json()
    if holder_keeps_the_number:
        assert error_text(response.json()) == COULD_NOT_VERIFY
    beta_holds_the_number.refresh_from_db()
    assert (beta_holds_the_number.phone_number == HELD_NUMBER) is holder_keeps_the_number
    assert TwilioChannel.objects.filter(channel=acme_channel).exists() is not holder_keeps_the_number


def test_the_ownership_check_gives_up_on_twilio_after_a_few_seconds(
    acme_admin_client, acme_channel, acme_secret, beta_holds_the_number
):
    twilio = _holder_owns_it(_acme_account(HELD_NUMBER))

    with _twilio(twilio):
        _create(acme_admin_client, acme_channel, acme_secret, HELD_NUMBER)

    assert twilio.timeouts == [3, 3]


def test_a_save_failing_on_another_constraint_is_not_reported_as_a_taken_number(
    acme_channel, acme_secret
):
    TwilioChannel.objects.create(
        channel=acme_channel, account_sid=ACME_ACCOUNT_SID, auth_token_secret=acme_secret
    )

    # A second Twilio row for the same channel breaks the primary key, not the number.
    with pytest.raises(IntegrityError):
        with TwilioService().claim_phone_number(
            channel=acme_channel,
            account_sid=ACME_ACCOUNT_SID,
            auth_token_secret=acme_secret,
            phone_number=None,
        ):
            TwilioChannel.objects.create(channel=acme_channel, account_sid=ACME_ACCOUNT_SID)


def test_a_holder_that_changes_its_account_while_it_is_checked_keeps_the_number(
    acme_admin_client, acme_channel, acme_secret, beta_holds_the_number
):
    """The verdict was about the old account, so the holder is not released on it."""
    fixed_account_sid = "AC" + "d" * 32
    twilio = _holder_has_no_numbers(_acme_account(HELD_NUMBER))

    def holder_fixes_its_account_meanwhile(account_sid, auth_token, url, **kwargs):
        answer = twilio(account_sid, auth_token, url, **kwargs)
        if account_sid == HOLDER_ACCOUNT_SID:
            TwilioChannel.objects.filter(pk=beta_holds_the_number.pk).update(
                account_sid=fixed_account_sid
            )
        return answer

    with _twilio(holder_fixes_its_account_meanwhile):
        response = _create(acme_admin_client, acme_channel, acme_secret, HELD_NUMBER)

    assert response.status_code == 400
    assert _phone_number_error(response) == ALREADY_USED
    assert not TwilioChannel.objects.filter(channel=acme_channel).exists()
    beta_holds_the_number.refresh_from_db()
    assert (beta_holds_the_number.phone_number, beta_holds_the_number.account_sid) == (
        HELD_NUMBER,
        fixed_account_sid,
    )


def test_a_number_a_third_channel_takes_after_the_release_leaves_the_holder_as_it_was(
    acme_admin_client, acme_channel, acme_secret, beta_holds_the_number, beta
):
    """The release and the owner's save are one write: losing the race undoes both."""
    third_channel = RealtimeChannel.objects.create(org=beta, name="Third line")

    def third_channel_saves_first(sender, instance, **kwargs):
        if instance.channel_id == acme_channel.pk:
            pre_save.disconnect(third_channel_saves_first, sender=TwilioChannel)
            TwilioChannel.objects.create(
                channel=third_channel, account_sid="AC" + "e" * 32, phone_number=HELD_NUMBER
            )

    twilio = _holder_has_no_numbers(_acme_account(HELD_NUMBER))
    pre_save.connect(third_channel_saves_first, sender=TwilioChannel, weak=False)
    try:
        with _twilio(twilio):
            response = _create(acme_admin_client, acme_channel, acme_secret, HELD_NUMBER)
    finally:
        pre_save.disconnect(third_channel_saves_first, sender=TwilioChannel)

    assert response.status_code == 400
    assert _phone_number_error(response) == ALREADY_USED
    assert not TwilioChannel.objects.filter(channel=acme_channel).exists()
    beta_holds_the_number.refresh_from_db()
    assert beta_holds_the_number.phone_number == HELD_NUMBER


@pytest.mark.parametrize(
    "twilio_error",
    [
        urllib.error.URLError("Name or service not known"),
        TimeoutError("timed out"),
        urllib.error.HTTPError("https://api.twilio.com", 503, "Unavailable", {}, io.BytesIO()),
        urllib.error.HTTPError("https://api.twilio.com", 429, "Too Many", {}, io.BytesIO()),
        json.JSONDecodeError("Expecting value", "<html>Bad gateway</html>", 0),
    ],
    ids=["unreachable", "timeout", "twilio-5xx", "twilio-rate-limit", "unreadable-body"],
)
def test_a_number_twilio_cannot_confirm_is_a_503_and_is_not_saved(
    acme_admin_client, acme_channel, acme_secret, beta_holds_the_number, twilio_error
):
    # An outage is not the user's input at fault, and it must not tell a number another
    # org holds apart from a free one.
    with _twilio(twilio_error):
        held = _create(acme_admin_client, acme_channel, acme_secret, HELD_NUMBER)
        free = _create(acme_admin_client, acme_channel, acme_secret, NOT_HELD_BY_ANYONE)

    assert held.status_code == free.status_code == 503
    assert held.json() == free.json()
    assert error_text(free.json()) == COULD_NOT_VERIFY
    assert not TwilioChannel.objects.filter(channel=acme_channel).exists()
    beta_holds_the_number.refresh_from_db()
    assert beta_holds_the_number.phone_number == HELD_NUMBER


@pytest.mark.parametrize("status", [401, 403, 404])
def test_credentials_twilio_rejects_are_reported_on_the_account_sid(
    acme_admin_client, acme_channel, acme_secret, status
):
    rejected = urllib.error.HTTPError("https://api.twilio.com", status, "", {}, io.BytesIO())

    with _twilio(rejected):
        response = _create(acme_admin_client, acme_channel, acme_secret, NOT_HELD_BY_ANYONE)

    assert _field_error(response, "account_sid") == CREDENTIALS_REJECTED
    assert not TwilioChannel.objects.filter(channel=acme_channel).exists()


def test_a_wrong_auth_token_is_reported_on_the_account_sid(acme_admin_client, acme, acme_channel):
    wrong_secret = secret_service.create(text="not-the-token", org=acme, name="WRONG_TOKEN")
    account = _acme_account(NOT_HELD_BY_ANYONE)

    with _twilio(account):
        response = _create(acme_admin_client, acme_channel, wrong_secret, NOT_HELD_BY_ANYONE)

    assert _field_error(response, "account_sid") == CREDENTIALS_REJECTED
    assert not TwilioChannel.objects.filter(channel=acme_channel).exists()


@pytest.mark.parametrize("method", ["patch", "put", "upsert-post"])
def test_changing_the_number_of_an_existing_channel_is_verified(
    acme_admin_client, acme_channel, acme_secret, beta_holds_the_number, method
):
    TwilioChannel.objects.create(
        channel=acme_channel, account_sid=ACME_ACCOUNT_SID, auth_token_secret=acme_secret
    )
    account = _acme_account()
    payload = {
        "channel": acme_channel.pk,
        "account_sid": ACME_ACCOUNT_SID,
        "auth_token_secret_id": acme_secret.pk,
        "phone_number": HELD_NUMBER,
    }

    with _twilio(account):
        if method == "upsert-post":
            response = acme_admin_client.post(TWILIO_CHANNELS_URL, payload, format="json")
        else:
            response = getattr(acme_admin_client, method)(
                f"{TWILIO_CHANNELS_URL}{acme_channel.pk}/", payload, format="json"
            )

    assert response.status_code == 400
    assert _phone_number_error(response) == NOT_IN_ACCOUNT
    assert TwilioChannel.objects.get(channel=acme_channel).phone_number is None


def test_an_unchanged_number_is_not_verified_again(acme_admin_client, acme_channel, acme_secret):
    # Saved before numbers were verified: it stays until its number changes.
    TwilioChannel.objects.create(
        channel=acme_channel,
        account_sid=ACME_ACCOUNT_SID,
        auth_token_secret=acme_secret,
        phone_number=NOT_HELD_BY_ANYONE,
    )

    with _twilio(urllib.error.URLError("must not be called")) as twilio:
        response = acme_admin_client.patch(
            f"{TWILIO_CHANNELS_URL}{acme_channel.pk}/",
            {"phone_number": NOT_HELD_BY_ANYONE, "account_sid": "AC" + "c" * 32},
            format="json",
        )

    assert response.status_code == 200, response.json()
    twilio.assert_not_called()
    stored = TwilioChannel.objects.get(channel=acme_channel)
    assert (stored.phone_number, stored.account_sid) == (NOT_HELD_BY_ANYONE, "AC" + "c" * 32)


def test_a_number_cannot_be_proven_without_an_auth_token(acme_admin_client, acme_channel):
    # The token secret was deleted for good: the link is cleared, the channel stays.
    TwilioChannel.objects.create(
        channel=acme_channel, account_sid=ACME_ACCOUNT_SID, auth_token_secret=None
    )

    with _twilio(urllib.error.URLError("must not be called")) as twilio:
        response = acme_admin_client.patch(
            f"{TWILIO_CHANNELS_URL}{acme_channel.pk}/",
            {"phone_number": NOT_HELD_BY_ANYONE},
            format="json",
        )

    assert response.status_code == 400, response.json()
    assert _field_error(response, "auth_token_secret_id") == NO_AUTH_TOKEN
    twilio.assert_not_called()
    assert TwilioChannel.objects.get(channel=acme_channel).phone_number is None


def test_a_number_cannot_be_proven_with_a_binned_auth_token(
    acme_admin_client, acme_channel, acme_secret
):
    # The channel keeps its link to a binned secret, but the token can't be read.
    TwilioChannel.objects.create(
        channel=acme_channel, account_sid=ACME_ACCOUNT_SID, auth_token_secret=acme_secret
    )
    acme_secret.delete()

    with _twilio(urllib.error.URLError("must not be called")) as twilio:
        response = acme_admin_client.patch(
            f"{TWILIO_CHANNELS_URL}{acme_channel.pk}/",
            {"phone_number": NOT_HELD_BY_ANYONE},
            format="json",
        )

    assert response.status_code == 400, response.json()
    assert _field_error(response, "auth_token_secret_id") == TOKEN_UNAVAILABLE
    twilio.assert_not_called()
    assert TwilioChannel.objects.get(channel=acme_channel).phone_number is None


def test_a_malformed_account_sid_is_reported_on_the_account_sid(
    acme_admin_client, acme_channel, acme_secret
):
    with _twilio(urllib.error.URLError("must not be called")) as twilio:
        response = _create(
            acme_admin_client,
            acme_channel,
            acme_secret,
            NOT_HELD_BY_ANYONE,
            account_sid="not-a-twilio-sid",
        )

    assert _field_error(response, "account_sid") == "Invalid account_sid"
    twilio.assert_not_called()
    assert not TwilioChannel.objects.filter(channel=acme_channel).exists()


@pytest.mark.parametrize("typed", ["+1 555 000 9999", "15550009999", "+1-555-000-9999"])
def test_a_number_not_in_e164_format_is_told_so_before_twilio_is_asked(
    acme_admin_client, acme_channel, acme_secret, typed
):
    with _twilio(urllib.error.URLError("must not be called")) as twilio:
        response = _create(acme_admin_client, acme_channel, acme_secret, typed)

    assert _phone_number_error(response) == NOT_E164
    twilio.assert_not_called()
    assert not TwilioChannel.objects.filter(channel=acme_channel).exists()


@pytest.mark.parametrize("cleared_to", [None, ""])
def test_clearing_the_number_needs_no_twilio(
    acme_admin_client, acme_channel, acme_secret, cleared_to
):
    TwilioChannel.objects.create(
        channel=acme_channel,
        account_sid=ACME_ACCOUNT_SID,
        auth_token_secret=acme_secret,
        phone_number=NOT_HELD_BY_ANYONE,
    )

    with _twilio(urllib.error.URLError("must not be called")) as twilio:
        response = acme_admin_client.patch(
            f"{TWILIO_CHANNELS_URL}{acme_channel.pk}/",
            {"phone_number": cleared_to},
            format="json",
        )

    assert response.status_code == 200, response.json()
    twilio.assert_not_called()
    assert TwilioChannel.objects.get(channel=acme_channel).phone_number is None


def test_a_number_taken_while_the_save_runs_is_a_400(
    acme_admin_client, acme_channel, acme_secret, beta
):
    """Two orgs that both prove the number get to save it; the unique constraint decides."""
    beta_channel = RealtimeChannel.objects.create(org=beta, name="Beta line")

    def beta_saves_first(sender, instance, **kwargs):
        if instance.channel_id == acme_channel.pk:
            pre_save.disconnect(beta_saves_first, sender=TwilioChannel)
            TwilioChannel.objects.create(
                channel=beta_channel, account_sid="AC" + "b" * 32, phone_number=HELD_NUMBER
            )

    account = _acme_account(HELD_NUMBER)
    pre_save.connect(beta_saves_first, sender=TwilioChannel, weak=False)
    try:
        with _twilio(account):
            response = _create(acme_admin_client, acme_channel, acme_secret, HELD_NUMBER)
    finally:
        pre_save.disconnect(beta_saves_first, sender=TwilioChannel)

    assert response.status_code == 400
    assert _phone_number_error(response) == ALREADY_USED
    assert not TwilioChannel.objects.filter(channel=acme_channel).exists()


def test_a_change_to_a_taken_number_leaves_the_channel_as_it_was(
    acme_admin_client, acme_channel, acme_secret, beta_holds_the_number
):
    TwilioChannel.objects.create(
        channel=acme_channel, account_sid=ACME_ACCOUNT_SID, auth_token_secret=acme_secret
    )
    other_account_sid = "AC" + "c" * 32
    account = _holder_owns_it(
        FakeTwilio().with_account(other_account_sid, ACME_AUTH_TOKEN, [HELD_NUMBER])
    )

    with _twilio(account):
        response = acme_admin_client.patch(
            f"{TWILIO_CHANNELS_URL}{acme_channel.pk}/",
            {"phone_number": HELD_NUMBER, "account_sid": other_account_sid},
            format="json",
        )

    assert response.status_code == 400
    assert _phone_number_error(response) == ALREADY_USED
    stored = TwilioChannel.objects.get(channel=acme_channel)
    assert (stored.phone_number, stored.account_sid) == (None, ACME_ACCOUNT_SID)


def test_a_cross_org_write_is_a_404_before_twilio_is_asked(
    acme_admin_client, acme_secret, beta_holds_the_number
):
    with _twilio(urllib.error.URLError("must not be called")) as twilio:
        response = _create(
            acme_admin_client, beta_holds_the_number.channel, acme_secret, NOT_HELD_BY_ANYONE
        )

    assert response.status_code == 404, response.json()
    twilio.assert_not_called()
    beta_holds_the_number.refresh_from_db()
    assert beta_holds_the_number.phone_number == HELD_NUMBER


def test_a_caller_without_secret_use_never_reaches_twilio(
    acme, acme_channel, acme_secret, django_user_model
):
    # On create, linking the token secret is a use of it: that check answers before Twilio.
    client = client_with_grants(
        org=acme,
        django_user_model=django_user_model,
        email="twilio-number-no-secret-use@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ),
            ResourceType.VOICE.value: FULL_CRUD,
        },
    )

    with _twilio(urllib.error.URLError("must not be called")) as twilio:
        response = _create(client, acme_channel, acme_secret, NOT_HELD_BY_ANYONE)

    assert _field_error(response, "auth_token_secret_id")
    twilio.assert_not_called()
    assert not TwilioChannel.objects.filter(channel=acme_channel).exists()
