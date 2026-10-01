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
    "read-only as `auth`: `{kind, secret_id, secret_tail}`, or null when the trigger "
    "has no auth; `secret_id` and `secret_tail` are null when the auth row has no "
    "secret, e.g. a bare `twilio` reservation. `secret_id` is the id only -- send it "
    "back unchanged as `auth_secret_id` to keep the current secret, which needs no "
    "secrets:USE permission). `auth_kind` picks which "
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


_TELEGRAM_BOT_KEY_REJECTED_422 = OpenApiResponse(
    description=(
        "Telegram answered 401 (unknown or revoked bot token) or 404 (malformed bot token) "
        "for the node's bot key."
    ),
    examples=[
        OpenApiExample(
            "Bot key rejected",
            value={
                "status_code": 422,
                "code": "telegram_bot_key_rejected",
                "message": (
                    "Telegram rejected this bot key. Check the secret selected as the bot "
                    "key on this node."
                ),
            },
            response_only=True,
            status_codes=["422"],
        ),
    ],
)


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
        "comparison ignores a trailing slash. `last_error_date` is ISO-8601 UTC. "
        "`registration_blocker` is `{code, message}` when this node's configuration makes "
        "registration impossible (checked without calling Telegram, by the same rules "
        "registration applies), else null. Codes: `no_webhook_trigger`, "
        "`no_tunnel_provider`, `localhost_provider`, `auth_kind_conflict`, "
        "`no_telegram_secret`, `invalid_telegram_secret`, `unresolvable_telegram_secret` "
        "(`no_bot_key` is answered with the 400 below instead). The bot key is never "
        "returned."
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
        422: _TELEGRAM_BOT_KEY_REJECTED_422,
        502: OpenApiResponse(
            description=(
                "Telegram was unreachable, answered another non-2xx (401/404 are the 422 "
                "above), or answered `ok: false`."
            ),
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


TELEGRAM_TRIGGER_NODE_REGISTER_WEBHOOK_POST = {
    "summary": "Register this node's webhook with Telegram now, taking over the bot key.",
    "description": (
        "Sends Telegram `setWebhook` for this node's callback URL even when EpicStaff "
        "believes it is already registered, overriding a URL another trigger sharing the "
        "bot key holds. A flow save only re-saves changed nodes, so this is how an "
        "unchanged node is re-registered. Takes no request body. On success the response "
        "is the same object as `GET .../webhook-info/`, read from Telegram after the "
        "registration. Configuration problems are checked first, without calling "
        "Telegram. Error messages are fixed text; the bot key is never returned."
    ),
    "request": None,
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
        403: OpenApiResponse(description="The caller lacks update permission on flows."),
        404: OpenApiResponse(description="No such node in the active organization."),
        409: OpenApiResponse(
            description=(
                "The node's configuration makes registration impossible. "
                "`registration_blocker` has the same shape and codes as in webhook-info."
            ),
            examples=[
                OpenApiExample(
                    "No Telegram secret on the trigger",
                    value={
                        "status_code": 409,
                        "code": "telegram_registration_blocked",
                        "message": (
                            "This node's configuration does not allow registering its webhook."
                        ),
                        "registration_blocker": {
                            "code": "no_telegram_secret",
                            "message": (
                                "No Telegram secret configured for this webhook trigger. Set "
                                "one via the trigger's `auth_secret_id` before registering."
                            ),
                        },
                    },
                    response_only=True,
                    status_codes=["409"],
                ),
            ],
        ),
        500: OpenApiResponse(
            description="The node's bot key secret could not be resolved (missing or not decryptable)."
        ),
        503: OpenApiResponse(
            description="The trigger's tunnel URL is not available.",
            examples=[
                OpenApiExample(
                    "Tunnel unavailable",
                    value={
                        "status_code": 503,
                        "code": "telegram_tunnel_unavailable",
                        "message": (
                            "The webhook tunnel is not available yet. Check the trigger's "
                            "tunnel and try again."
                        ),
                    },
                    response_only=True,
                    status_codes=["503"],
                ),
            ],
        ),
        422: _TELEGRAM_BOT_KEY_REJECTED_422,
        502: OpenApiResponse(
            description=(
                "Telegram was unreachable or rejected the registration (one attempt; "
                "the user can retry). If registration succeeds but the follow-up "
                "webhook-info read fails, the response is still 200, built from what "
                "`setWebhook` confirmed."
            ),
            examples=[
                OpenApiExample(
                    "Registration failed",
                    value={
                        "status_code": 502,
                        "code": "telegram_registration_failed",
                        "message": (
                            "Telegram could not register the webhook. Check the panel "
                            "status and try again."
                        ),
                    },
                    response_only=True,
                    status_codes=["502"],
                ),
            ],
        ),
    },
}
