"""Twilio REST API integration for `TwilioChannel`: SID format validation,
the raw authenticated REST call, phone-number lookup, and voice-webhook
(VoiceUrl) configuration.

Extracted from `tables/views/model_view_sets.py`'s Twilio views so those views only translate
request data into a service call and a typed `TwilioServiceError` into the
exact `Response({"error": ...}, status=...)` they produced before this
refactor -- the response contract (body shape, status codes, message
strings) is unchanged.
"""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
import re

from tables.models.webhook_models import RealtimeChannel
from tables.services.secrets import secret_resolver
from tables.services.webhook_trigger_service import WebhookTriggerService
from utils.logger import logger
from utils.singleton_meta import SingletonMeta

_TWILIO_PHONE_SID_RE = re.compile(r"^PN[0-9a-fA-F]{32}$")
_TWILIO_ACCOUNT_SID_RE = re.compile(r"^AC[0-9a-fA-F]{32}$")


class TwilioServiceError(Exception):
    """Base for every typed error `TwilioService` raises.

    Carries the exact `(message, status_code)` pair the caller must
    reproduce verbatim as `Response({"error": message}, status=status_code)`
    -- this is what lets the views stay thin translators instead of
    re-deciding status codes/messages themselves.
    """

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TwilioNotFoundError(TwilioServiceError):
    """Channel/token not found, or not visible to the caller's org -- 404.

    Existence is never leaked: an unknown token and a token belonging to
    another org both raise this with the same generic message.
    """

    def __init__(self, message: str = "Channel not found"):
        super().__init__(message, status_code=404)


class TwilioValidationError(TwilioServiceError):
    """Malformed input or an unmet precondition -- 400."""

    def __init__(self, message: str):
        super().__init__(message, status_code=400)


def _twilio_request(
    account_sid: str, auth_token: str, url: str, method: str = "GET", data: dict = None
):
    """Make an authenticated request to the Twilio REST API."""
    credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}", "Accept": "application/json"}
    body = None
    if data:
        encoded = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = encoded
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
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
            raise TwilioValidationError(
                "Failed to retrieve phone numbers from Twilio"
            ) from e
        except Exception as e:
            raise TwilioServiceError(str(e), status_code=502) from e

    def configure_webhook(self, phone_sid: str, channel_token: str, org_id: int) -> str:
        """Set the VoiceUrl on a Twilio phone number to this channel's voice
        webhook URL. Returns the resulting webhook_url.

        Credentials and the target channel are org-owned (RealtimeChannel is
        an OrgScopedModel) -- org isolation is the
        boundary here, not a superadmin gate: any authenticated member of
        the channel's own org may configure their own org's Twilio number. A
        channel belonging to another org (or none at all) is rejected
        exactly like a missing token, so existence never leaks.
        """
        logger.info(
            f"configure-webhook: phone_sid={phone_sid} channel_token={channel_token}"
        )

        if not phone_sid or not channel_token:
            logger.warning("configure-webhook: missing phone_sid or channel_token")
            raise TwilioValidationError("phone_sid and channel_token are required")

        self.validate_phone_sid(phone_sid)

        try:
            token = uuid.UUID(str(channel_token))
        except (ValueError, AttributeError, TypeError):
            logger.warning(
                f"configure-webhook: malformed channel_token={channel_token}"
            )
            raise TwilioNotFoundError()

        try:
            channel = RealtimeChannel.objects.select_related(
                "twilio__webhook_trigger__ngrok", "twilio__webhook_trigger__localhost"
            ).get(token=token)
        except RealtimeChannel.DoesNotExist:
            logger.warning(
                f"configure-webhook: channel not found for token={channel_token}"
            )
            raise TwilioNotFoundError()

        twilio = getattr(channel, "twilio", None)
        if channel.org_id != org_id:
            logger.warning(
                f"configure-webhook: channel {channel.id} does not belong to "
                f"the active org ({org_id})"
            )
            raise TwilioNotFoundError()
        if not twilio or not twilio.account_sid or twilio.auth_token_secret_id is None:
            logger.warning(
                f"configure-webhook: no Twilio credentials for channel {channel.id}"
            )
            raise TwilioValidationError(
                "No Twilio credentials configured for this channel"
            )

        account_sid = twilio.account_sid
        try:
            self.validate_account_sid(account_sid)
        except TwilioValidationError:
            logger.warning(
                f"configure-webhook: invalid account_sid for channel {channel.id}"
            )
            raise

        auth_token = secret_resolver.resolve(
            secret_id=twilio.auth_token_secret_id,
            org_id=channel.org_id,
            context="TwilioChannel.auth_token",
        )
        logger.info(
            f"configure-webhook: using stored credentials for account_sid={account_sid}"
        )

        webhook_trigger = twilio.webhook_trigger
        logger.info(f"configure-webhook: webhook_trigger={webhook_trigger}")
        if not webhook_trigger or not webhook_trigger.provider_type:
            logger.warning(
                f"configure-webhook: no webhook trigger configured for channel {channel.id}"
            )
            raise TwilioValidationError(
                "No webhook trigger configured for this channel"
            )

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
        logger.info(
            f"configure-webhook: setting VoiceUrl={webhook_url} on phone_sid={phone_sid}"
        )

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
            return webhook_url
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            logger.error(f"configure-webhook: Twilio HTTP error {e.code}: {body}")
            raise TwilioServiceError(
                "Failed to configure Twilio webhook", status_code=e.code
            ) from e
        except Exception as e:
            logger.exception("configure-webhook: unexpected error")
            raise TwilioServiceError(str(e), status_code=502) from e
