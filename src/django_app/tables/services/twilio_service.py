"""Twilio REST API integration for `TwilioChannel`: SID format validation,
the raw authenticated REST call, phone-number lookup, and voice-webhook
(VoiceUrl) configuration.

Extracted from `tables/views/model_view_sets.py`'s Twilio views so those views only translate
request data into a service call; a typed `TwilioServiceError` reaches the exception
handler, which renders it with its own status and code.
"""

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from typing import NamedTuple

from django.db import IntegrityError, transaction
from src.shared.models import UserAction
from tables.models.secret_models import Secret
from tables.models.webhook_models import RealtimeChannel, TwilioChannel
from tables.services.secrets import SecretResolutionError, secret_resolver
from tables.services.webhook_trigger_service import WebhookTriggerService
from user_audit.recorder import record_user_action
from utils.exceptions import CustomAPIExeption
from utils.logger import logger
from utils.singleton_meta import SingletonMeta

_TWILIO_PHONE_SID_RE = re.compile(r"^PN[0-9a-fA-F]{32}$")
_TWILIO_ACCOUNT_SID_RE = re.compile(r"^AC[0-9a-fA-F]{32}$")
# Twilio stores and returns every incoming number in E.164.
_E164_PHONE_NUMBER_RE = re.compile(r"^\+[1-9][0-9]{1,14}$")
_LIVE_PHONE_NUMBER_CONSTRAINT = "unique_live_twilio_phone_number"
# Twilio's answers to an account SID / auth token pair it does not accept.
_REJECTED_CREDENTIALS_STATUSES = frozenset({401, 403, 404})
# Releasing a number on a 404 would take it from another org on an answer that may be
# Twilio's own glitch: only an outright authentication refusal judges a holder.
_HOLDER_REJECTED_CREDENTIALS_STATUSES = frozenset({401, 403})
# Short, so a bulk restore during an outage fails each numbered channel in seconds.
_OWNERSHIP_CHECK_TIMEOUT_SECONDS = 3

_TWILIO_CREDENTIALS_REJECTED_MESSAGE = "Twilio rejected the account SID or auth token."
_PHONE_NUMBER_UNVERIFIED_MESSAGE = "Could not verify the phone number with Twilio. Try again later."
_PHONE_NUMBER_NOT_E164_MESSAGE = "Enter the phone number in E.164 format, for example +15550001234."
_PHONE_NUMBER_NOT_IN_ACCOUNT_MESSAGE = "This phone number is not in the given Twilio account."
_PHONE_NUMBER_ALREADY_USED_MESSAGE = "This phone number is already used by another voice channel."
_NO_AUTH_TOKEN_MESSAGE = "No Twilio credentials configured for this channel"
_AUTH_TOKEN_UNAVAILABLE_MESSAGE = "The Twilio auth token is unavailable; restore or replace it."


class TwilioServiceError(CustomAPIExeption):
    """Base for every typed error `TwilioService` raises: a call to Twilio failed.

    The message is always one of this module's fixed sentences, never Twilio's
    response or an exception's text, so the exception handler shows it as it is.
    """

    status_code = 502
    default_code = "twilio_request_failed"

    def __init__(self, message: str):
        super().__init__(detail=message)


class TwilioNotFoundError(TwilioServiceError):
    """Channel/token not found, or not visible to the caller's org -- 404.

    Existence is never leaked: an unknown token and a token belonging to
    another org both raise this with the same generic message.
    """

    status_code = 404
    default_code = "twilio_channel_not_found"

    def __init__(self, message: str = "Channel not found"):
        super().__init__(message)


class TwilioValidationError(TwilioServiceError):
    """Malformed input or an unmet precondition -- 400."""

    status_code = 400
    default_code = "twilio_invalid_request"

    def __init__(self, message: str):
        super().__init__(message)


class TwilioNoAnswerError(TwilioServiceError):
    """Twilio couldn't be reached or gave no usable answer -- 503.

    The question asked is neither proven nor disproven: callers must change nothing.
    """

    status_code = 503
    # Shared with TwilioUnavailableError on purpose: callers re-raise this as that error,
    # and to a client both mean the same thing.
    default_code = "twilio_unavailable"

    def __init__(self):
        super().__init__(_PHONE_NUMBER_UNVERIFIED_MESSAGE)


class TwilioCredentialsRejectedError(TwilioValidationError):
    """Twilio refused the account SID / auth token pair -- 400."""

    def __init__(self):
        super().__init__(_TWILIO_CREDENTIALS_REJECTED_MESSAGE)


class PhoneNumberClaimRefusal(StrEnum):
    """Why a channel may not save a phone number; the caller maps it to the input at fault."""

    NOT_E164 = "not_e164"
    INVALID_ACCOUNT_SID = "invalid_account_sid"
    NO_AUTH_TOKEN = "no_auth_token"
    AUTH_TOKEN_UNAVAILABLE = "auth_token_unavailable"
    CREDENTIALS_REJECTED = "credentials_rejected"
    NOT_IN_ACCOUNT = "not_in_account"
    ALREADY_USED = "already_used"


class TwilioPhoneNumberClaimError(TwilioValidationError):
    """A channel may not save this phone number -- 400; `reason` says why."""

    def __init__(self, reason: PhoneNumberClaimRefusal, message: str):
        super().__init__(message)
        self.reason = reason


class _UnprovenHolder(NamedTuple):
    """A live channel holding a number its own Twilio account couldn't prove, and why."""

    twilio_channel: TwilioChannel
    refusal: PhoneNumberClaimRefusal


def _log_and_wrap_unexpected_twilio_error(operation: str, error: Exception) -> TwilioServiceError:
    """Log an unexpected failure of a Twilio call and return the generic 502 to raise.

    The error's text never reaches the client: it can name internal hosts or
    describe our own code failing. It is logged without a traceback, because
    loguru's `diagnose` would print the auth token and the Basic credentials
    held in `_twilio_request`'s local variables.
    """
    logger.error(
        "{operation}: unexpected error calling Twilio: {error_type}: {error}",
        operation=operation,
        error_type=type(error).__name__,
        error=str(error),
    )
    return TwilioServiceError("Failed to communicate with Twilio")


def _twilio_request(
    account_sid: str,
    auth_token: str,
    url: str,
    method: str = "GET",
    data: dict | None = None,
    timeout: float = 10,
):
    """Make an authenticated request to the Twilio REST API; `timeout` is per socket operation."""
    credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}", "Accept": "application/json"}
    body = None
    if data:
        encoded = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = encoded
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


class TwilioService(metaclass=SingletonMeta):
    """No injected dependencies: `secret_resolver` is a module-level
    singleton imported directly here, matching the existing convention at
    every other `secret_resolver.resolve(...)` call site in this codebase
    (e.g. `converter_service.py`, `telegram_trigger_service.py`) rather than
    being constructor-injected like `redis_service`/`converter_service` are
    into `WebhookTriggerService`.
    """

    def validate_account_sid(self, account_sid: str) -> None:
        if not _TWILIO_ACCOUNT_SID_RE.fullmatch(account_sid or ""):
            raise TwilioValidationError("Invalid account_sid")

    def validate_phone_sid(self, phone_sid: str) -> None:
        if not _TWILIO_PHONE_SID_RE.fullmatch(phone_sid or ""):
            raise TwilioValidationError("Invalid phone_sid")

    def get_phone_numbers(self, account_sid: str, auth_token: str) -> list[dict]:
        """Call Twilio's IncomingPhoneNumbers API and shape the response.

        Sole caller is `TwilioChannelViewSet.phone_numbers` (credentials
        resolved from a stored `Secret`). The legacy header-based
        `TwilioPhoneNumbersView` (raw account_sid/auth_token via headers,
        superadmin-only) was removed on `main` — superseded by the
        org-scoped `TwilioChannel` model.
        """
        self.validate_account_sid(account_sid)
        try:
            url = (
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"
                "/IncomingPhoneNumbers.json?PageSize=100"
            )
            data = _twilio_request(account_sid, auth_token, url)
            return [
                {
                    "sid": n["sid"],
                    "phone_number": n["phone_number"],
                    "friendly_name": n["friendly_name"],
                    "voice_url": n.get("voice_url") or "",
                }
                for n in data.get("incoming_phone_numbers", [])
            ]
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            logger.error(f"twilio phone-numbers: Twilio HTTP error {e.code}: {body}")
            raise TwilioValidationError("Failed to retrieve phone numbers from Twilio") from e
        except Exception as e:
            raise _log_and_wrap_unexpected_twilio_error("twilio phone-numbers", e) from e

    def account_owns_number(
        self,
        account_sid: str,
        auth_token: str,
        phone_number: str,
        *,
        rejected_statuses: frozenset[int] = _REJECTED_CREDENTIALS_STATUSES,
    ) -> bool:
        """Return whether `phone_number` is one of the account's incoming phone numbers.

        Asks Twilio for this one number rather than listing the account, so an account
        with more numbers than one page holds is answered right. Twilio's `PhoneNumber`
        filter also matches partially, so the answer is compared exactly. Twilio gets
        a few seconds to answer.

        Args:
            rejected_statuses: The HTTP statuses that mean Twilio refused the
                credentials; any other error status is no answer.

        Raises:
            TwilioValidationError: `account_sid` is malformed.
            TwilioCredentialsRejectedError: Twilio rejected the account SID / auth token pair.
            TwilioNoAnswerError: Twilio could not be reached or failed to answer.
                Callers must treat this as "not proven", never as "owned".
        """
        self.validate_account_sid(account_sid)
        query = urllib.parse.urlencode({"PhoneNumber": phone_number})
        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"
            f"/IncomingPhoneNumbers.json?{query}"
        )
        try:
            data = _twilio_request(
                account_sid, auth_token, url, timeout=_OWNERSHIP_CHECK_TIMEOUT_SECONDS
            )
        except urllib.error.HTTPError as error:
            logger.warning("twilio account-owns-number: Twilio HTTP error {code}", code=error.code)
            if error.code in rejected_statuses:
                raise TwilioCredentialsRejectedError() from error
            raise TwilioNoAnswerError() from error
        # URLError, socket timeouts and an unreadable body: Twilio gave no answer.
        except (OSError, ValueError) as error:
            logger.warning(
                "twilio account-owns-number: no answer from Twilio: {error_type}",
                error_type=type(error).__name__,
            )
            raise TwilioNoAnswerError() from error
        return any(
            number.get("phone_number") == phone_number
            for number in data.get("incoming_phone_numbers", [])
        )

    @contextmanager
    def claim_phone_number(
        self,
        *,
        channel: RealtimeChannel,
        account_sid: str,
        auth_token_secret: Secret | None,
        phone_number: str | None,
        current_phone_number: str | None = None,
    ) -> Iterator[None]:
        """Run a channel's save so that it stores a new phone number only once proven.

        A number is unique among live channels of every organization, so checking
        uniqueness first would tell any caller whether another org uses a number and
        let it claim the number first. Ownership is therefore proven first: Twilio is
        asked with the channel's own account SID and auth token, and a number the
        account doesn't hold gets one answer whether or not it is taken.

        Only a proven owner reaches the live channel already holding the number (of any
        org), and that holder is asked about the same way, with its own credentials. A
        holder Twilio confirms keeps the number: the save then hits the live-number
        constraint and is refused ALREADY_USED, so a tie goes to the holder. A holder
        that can't prove it (not in its account, credentials refused with a 401 or 403,
        missing or unreadable token, malformed SID) loses the number in the same
        transaction as the save, which frees numbers saved before ownership was checked
        or brought back by an earlier restore. Both Twilio calls run before any row is
        locked.

        The save runs in the body. The constraint decides the final write, so a
        concurrent claim is refused ALREADY_USED and undoes the release too. No number,
        or the number the channel already has, needs no check: nothing is sent to
        Twilio. The caller must have run the org, permission and secret Use checks:
        this sends the channel's auth token to Twilio.

        Args:
            account_sid: The SID the channel will have after the write.
            auth_token_secret: The token secret the channel will have after the write.
            current_phone_number: The stored number; None for a new channel.

        Raises:
            TwilioPhoneNumberClaimError: The number can't be saved; `reason` says why.
            TwilioNoAnswerError: Twilio could not be reached or failed to answer, for the
                channel or for the holder; any other error status for the holder counts
                as no answer too. Nothing was changed.
        """
        unproven_holder = None
        if phone_number and phone_number != current_phone_number:
            if not _E164_PHONE_NUMBER_RE.fullmatch(phone_number):
                raise TwilioPhoneNumberClaimError(
                    PhoneNumberClaimRefusal.NOT_E164, _PHONE_NUMBER_NOT_E164_MESSAGE
                )
            self._prove_ownership(
                org_id=channel.org_id,
                account_sid=account_sid,
                auth_token_secret_id=auth_token_secret.pk if auth_token_secret else None,
                phone_number=phone_number,
            )
            unproven_holder = self._unproven_holder(phone_number, claimant_id=channel.pk)
        with transaction.atomic():
            if unproven_holder is not None:
                self._release_phone_number(unproven_holder, phone_number, claimant_id=channel.pk)
            with self._phone_number_conflict_as_claim_error():
                yield

    def stored_number_refusal(
        self, twilio_channel: TwilioChannel
    ) -> PhoneNumberClaimRefusal | None:
        """Return why a stored channel's own Twilio account can't prove its number, or None.

        Asks Twilio with the channel's stored account SID and its org's auth token
        secret; nothing is sent when the SID is malformed or the token is missing or
        unreadable. Reads the org through `twilio_channel.channel`: select it along.

        Raises:
            TwilioNoAnswerError: Twilio could not be reached or failed to answer.
                Ownership is neither proven nor disproven.
        """
        return self._stored_number_refusal(twilio_channel, _REJECTED_CREDENTIALS_STATUSES)

    def _stored_number_refusal(
        self, twilio_channel: TwilioChannel, rejected_statuses: frozenset[int]
    ) -> PhoneNumberClaimRefusal | None:
        try:
            self._prove_ownership(
                org_id=twilio_channel.channel.org_id,
                account_sid=twilio_channel.account_sid,
                auth_token_secret_id=twilio_channel.auth_token_secret_id,
                phone_number=twilio_channel.phone_number,
                rejected_statuses=rejected_statuses,
            )
        except TwilioPhoneNumberClaimError as refusal:
            return refusal.reason
        return None

    def _prove_ownership(
        self,
        *,
        org_id: int,
        account_sid: str,
        auth_token_secret_id: int | None,
        phone_number: str,
        rejected_statuses: frozenset[int] = _REJECTED_CREDENTIALS_STATUSES,
    ) -> None:
        # `account_owns_number` validates the SID too; checking it here first tags the
        # refusal INVALID_ACCOUNT_SID, so the caller reports it on the account SID field.
        try:
            self.validate_account_sid(account_sid)
        except TwilioValidationError as error:
            raise TwilioPhoneNumberClaimError(
                PhoneNumberClaimRefusal.INVALID_ACCOUNT_SID, str(error.detail)
            ) from None
        auth_token = self._resolve_auth_token(org_id, auth_token_secret_id)
        try:
            owned = self.account_owns_number(
                account_sid, auth_token, phone_number, rejected_statuses=rejected_statuses
            )
        except TwilioCredentialsRejectedError as error:
            raise TwilioPhoneNumberClaimError(
                PhoneNumberClaimRefusal.CREDENTIALS_REJECTED, str(error.detail)
            ) from None
        if not owned:
            raise TwilioPhoneNumberClaimError(
                PhoneNumberClaimRefusal.NOT_IN_ACCOUNT, _PHONE_NUMBER_NOT_IN_ACCOUNT_MESSAGE
            )

    def _unproven_holder(self, phone_number: str, claimant_id: int) -> _UnprovenHolder | None:
        # The live-number constraint allows one holder at most.
        holder = (
            TwilioChannel.objects.select_related("channel")
            .filter(phone_number=phone_number)
            .exclude(pk=claimant_id)
            .first()
        )
        if holder is None:
            return None
        refusal = self._stored_number_refusal(holder, _HOLDER_REJECTED_CREDENTIALS_STATUSES)
        return None if refusal is None else _UnprovenHolder(holder, refusal)

    @staticmethod
    def _release_phone_number(
        unproven_holder: _UnprovenHolder, phone_number: str, claimant_id: int
    ) -> None:
        holder = unproven_holder.twilio_channel
        # The UPDATE locks the row and re-checks it under the lock: a holder whose number,
        # account or token changed since Twilio was asked was not judged on what it has
        # now, so it keeps its number and the constraint decides.
        released = TwilioChannel.objects.filter(
            pk=holder.pk,
            phone_number=phone_number,
            account_sid=holder.account_sid,
            auth_token_secret_id=holder.auth_token_secret_id,
        ).update(phone_number=None)
        if released:
            logger.warning(
                "twilio phone-number claim: channel {holder_id} lost its phone number to "
                "channel {claimant_id}: its Twilio account could not prove it ({refusal})",
                holder_id=holder.pk,
                claimant_id=claimant_id,
                refusal=unproven_holder.refusal.value,
            )

    @contextmanager
    def _phone_number_conflict_as_claim_error(self) -> Iterator[None]:
        """Turn a save that hits the live-number constraint into an ALREADY_USED refusal.

        The savepoint rolls the failed save back and keeps a caller's outer transaction
        usable after the IntegrityError.
        """
        try:
            with transaction.atomic():
                yield
        except IntegrityError as error:
            diagnostics = getattr(error.__cause__, "diag", None)
            if getattr(diagnostics, "constraint_name", None) != _LIVE_PHONE_NUMBER_CONSTRAINT:
                raise
            raise TwilioPhoneNumberClaimError(
                PhoneNumberClaimRefusal.ALREADY_USED, _PHONE_NUMBER_ALREADY_USED_MESSAGE
            ) from None

    @staticmethod
    def _resolve_auth_token(org_id: int, auth_token_secret_id: int | None) -> str:
        # Deleted for good clears the link; a binned secret is still linked but unreadable.
        if auth_token_secret_id is None:
            raise TwilioPhoneNumberClaimError(
                PhoneNumberClaimRefusal.NO_AUTH_TOKEN, _NO_AUTH_TOKEN_MESSAGE
            )
        try:
            return secret_resolver.resolve(
                secret_id=auth_token_secret_id,
                org_id=org_id,
                context="TwilioChannel.auth_token",
            )
        except SecretResolutionError:
            raise TwilioPhoneNumberClaimError(
                PhoneNumberClaimRefusal.AUTH_TOKEN_UNAVAILABLE, _AUTH_TOKEN_UNAVAILABLE_MESSAGE
            ) from None

    def configure_webhook(self, phone_sid: str, channel_token: str, org_id: int) -> str:
        """Set the VoiceUrl on a Twilio phone number to this channel's voice
        webhook URL. Returns the resulting webhook_url.

        Credentials and the target channel are org-owned (RealtimeChannel is
        an OrgScopedModel) -- org isolation is the
        boundary here, not a superadmin gate: any authenticated member of
        the channel's own org may configure their own org's Twilio number. A
        channel belonging to another org (or none at all) is rejected
        exactly like a missing token, so existence never leaks.

        Records the channel as updated once Twilio has taken the new URL.
        """
        logger.info(f"configure-webhook: phone_sid={phone_sid} channel_token={channel_token}")

        if not phone_sid or not channel_token:
            logger.warning("configure-webhook: missing phone_sid or channel_token")
            raise TwilioValidationError("phone_sid and channel_token are required")

        self.validate_phone_sid(phone_sid)

        try:
            token = uuid.UUID(str(channel_token))
        except (ValueError, AttributeError, TypeError) as e:
            logger.warning(f"configure-webhook: malformed channel_token={channel_token}")
            raise TwilioNotFoundError() from e

        try:
            channel = RealtimeChannel.enabled_objects.select_related(
                "twilio__webhook_trigger__ngrok", "twilio__webhook_trigger__localhost"
            ).get(token=token)
        except RealtimeChannel.DoesNotExist as e:
            logger.warning(
                f"configure-webhook: channel not found or disabled for token={channel_token}"
            )
            raise TwilioNotFoundError() from e

        twilio = getattr(channel, "twilio", None)
        if channel.org_id != org_id:
            logger.warning(
                f"configure-webhook: channel {channel.id} does not belong to "
                f"the active org ({org_id})"
            )
            raise TwilioNotFoundError()
        if not twilio or not twilio.account_sid or twilio.auth_token_secret_id is None:
            logger.warning(f"configure-webhook: no Twilio credentials for channel {channel.id}")
            raise TwilioValidationError(_NO_AUTH_TOKEN_MESSAGE)

        account_sid = twilio.account_sid
        try:
            self.validate_account_sid(account_sid)
        except TwilioValidationError:
            logger.warning(f"configure-webhook: invalid account_sid for channel {channel.id}")
            raise

        auth_token = secret_resolver.resolve(
            secret_id=twilio.auth_token_secret_id,
            org_id=channel.org_id,
            context="TwilioChannel.auth_token",
        )
        logger.info(f"configure-webhook: using stored credentials for account_sid={account_sid}")

        webhook_trigger = twilio.webhook_trigger
        logger.info(f"configure-webhook: webhook_trigger={webhook_trigger}")
        if not webhook_trigger or not webhook_trigger.provider_type:
            logger.warning(
                f"configure-webhook: no webhook trigger configured for channel {channel.id}"
            )
            raise TwilioValidationError("No webhook trigger configured for this channel")

        provider_error = twilio.validate_provider()
        if provider_error:
            logger.warning(
                f"configure-webhook: provider validation failed for channel {channel.id}: {provider_error}"
            )
            raise TwilioValidationError(provider_error)

        tunnel_url = WebhookTriggerService().get_tunnel_url_for_trigger(webhook_trigger)
        if not tunnel_url:
            active_config = webhook_trigger.get_active_config()
            if active_config:
                tunnel_url = active_config.get_webhook_url()
        logger.info(f"configure-webhook: tunnel_url={tunnel_url}")
        if not tunnel_url:
            logger.warning(
                f"configure-webhook: webhook trigger {webhook_trigger.id} has no live URL and no domain"
            )
            raise TwilioValidationError(
                "Webhook tunnel is not running and has no domain configured"
            )

        webhook_url = f"{tunnel_url.rstrip('/')}/voice/{channel_token}"
        logger.info(f"configure-webhook: setting VoiceUrl={webhook_url} on phone_sid={phone_sid}")

        try:
            url = (
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"
                f"/IncomingPhoneNumbers/{phone_sid}.json"
            )
            _twilio_request(
                account_sid,
                auth_token,
                url,
                method="POST",
                data={"VoiceUrl": webhook_url, "VoiceMethod": "POST"},
            )
            logger.info(f"configure-webhook: success webhook_url={webhook_url}")
            record_user_action(action=UserAction.UPDATED, org_id=channel.org_id, target=channel)
            return webhook_url
        except urllib.error.HTTPError as e:
            # Twilio's status describes our request to Twilio, not the client's request to
            # us, so every Twilio HTTP failure is a 502; its status and body go to the log.
            logger.error(
                "configure-webhook: Twilio HTTP error {status}: {body}",
                status=e.code,
                body=e.read().decode(),
            )
            raise TwilioServiceError("Failed to configure Twilio webhook") from e
        except Exception as e:
            raise _log_and_wrap_unexpected_twilio_error("configure-webhook", e) from e
