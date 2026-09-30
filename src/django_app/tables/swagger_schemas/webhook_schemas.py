from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.serializers.model_serializers import TelegramWebhookInfoSerializer
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

WEBHOOK_TRIGGER_NODE_CREATE = {
    "description": (
        "Auth for this node's inbound webhook is not configured here -- it "
        "lives on the linked `webhook_trigger` (see `/webhook-triggers/`), "
        "not on the node."
    ),
}

WEBHOOK_TRIGGER_NODE_UPDATE = {}

WEBHOOK_TRIGGER_NODE_PARTIAL_UPDATE = {}

_WEBHOOK_TRIGGER_AUTH_DESCRIPTION = (
    "`auth_secret_id` sets/updates this trigger's user-settable auth "
    "strategy secret (write-only; the resolved state is echoed back "
    "read-only as `auth`: `{kind, secret_tail}`). `auth_kind` picks which "
    "strategy -- `webhook` (`EPICSTAFF_API_KEY`, default if omitted and no "
    "auth exists yet) or `telegram` (`X-Telegram-Bot-Api-Secret-Token`; "
    "must be 1-256 characters using only `A-Z a-z 0-9 _ -`, a constraint "
    "from Telegram's own Bot API). Setting a `telegram` secret immediately "
    "resyncs (re-calls `setWebhook` for) any Telegram trigger nodes already "
    "attached to this trigger. A trigger already used by a Twilio channel "
    "manages its own auth automatically and rejects `auth_secret_id`. "
    "There is no disable toggle: auth is mandatory once a secret is set. "
    "If a `telegram` secret update saves successfully but the immediate "
    "`setWebhook` resync fails for one or more attached nodes (e.g. tunnel "
    "not up yet, Telegram API error), the response still returns 200/201 "
    "with the new secret persisted, plus a `telegram_registration_warning` "
    "string field describing which node(s) failed and that a retry is "
    "needed -- the request is not failed outright since the user's secret "
    "was correctly saved."
)

WEBHOOK_TRIGGER_CREATE = {"description": _WEBHOOK_TRIGGER_AUTH_DESCRIPTION}

WEBHOOK_TRIGGER_UPDATE = {"description": _WEBHOOK_TRIGGER_AUTH_DESCRIPTION}

WEBHOOK_TRIGGER_PARTIAL_UPDATE = {"description": _WEBHOOK_TRIGGER_AUTH_DESCRIPTION}


TELEGRAM_TRIGGER_NODE_WEBHOOK_INFO_GET = {
    "summary": "Return the webhook URL Telegram has registered for this node's bot key.",
    "description": (
        "Calls Telegram's `getWebhookInfo` for the node's bot key (one attempt, short "
        "timeout) and compares the result with this node's own callback URL "
        "(`<tunnel>/webhooks/<path>/`). Telegram keeps only the last `setWebhook` URL "
        "per bot key, so when several Telegram trigger nodes share a key only one of "
        "them receives messages -- `is_match: false` flags a node that is not it. "
        "`registered_url` is null when Telegram has no webhook set. `expected_url` is "
        "null when the node has no webhook trigger, the trigger has no tunnel "
        "provider, uses the localhost provider, or its tunnel URL is not currently "
        "available. `is_match` is false when Telegram has no webhook set, and null "
        "only when `expected_url` is null (the match cannot be determined); the "
        "comparison ignores a trailing slash. `last_error_date` is ISO-8601 UTC. The "
        "bot key is never returned."
    ),
    "responses": {
        200: TelegramWebhookInfoSerializer,
        400: OpenApiResponse(
            description="The node has no bot key configured.",
            examples=[
                OpenApiExample(
                    "No bot key",
                    value={
                        "status_code": 400,
                        "code": "telegram_bot_key_not_configured",
                        "message": "This Telegram trigger node has no bot key configured.",
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(description="The caller lacks read permission on flows."),
        404: OpenApiResponse(description="No such node in the active organization."),
        500: OpenApiResponse(
            description="The node's bot key secret could not be resolved (missing or not decryptable, e.g. after an encryption key rotation)."
        ),
        502: OpenApiResponse(
            description="Telegram was unreachable, answered non-2xx, or answered `ok: false`.",
            examples=[
                OpenApiExample(
                    "Telegram unavailable",
                    value={
                        "status_code": 502,
                        "code": "telegram_webhook_info_unavailable",
                        "message": "Could not fetch webhook info from Telegram.",
                    },
                    response_only=True,
                    status_codes=["502"],
                ),
            ],
        ),
    },
}
