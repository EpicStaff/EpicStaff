from drf_spectacular.utils import (
    OpenApiResponse,
    OpenApiExample,
)
from drf_spectacular.types import OpenApiTypes
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

WEBHOOK_TRIGGER_NODE_CREATE = dict(
    description=(
        "Auth for this node's inbound webhook is not configured here -- it "
        "lives on the linked `webhook_trigger` (see `/webhook-triggers/`), "
        "not on the node."
    ),
)

WEBHOOK_TRIGGER_NODE_UPDATE = dict()

WEBHOOK_TRIGGER_NODE_PARTIAL_UPDATE = dict()

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

WEBHOOK_TRIGGER_CREATE = dict(description=_WEBHOOK_TRIGGER_AUTH_DESCRIPTION)

WEBHOOK_TRIGGER_UPDATE = dict(description=_WEBHOOK_TRIGGER_AUTH_DESCRIPTION)

WEBHOOK_TRIGGER_PARTIAL_UPDATE = dict(description=_WEBHOOK_TRIGGER_AUTH_DESCRIPTION)

REGISTER_WEBHOOKS_POST = dict(
    summary="Register webhooks",
    description="Triggers registration of all webhooks via the webhook trigger service.",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="OK",
            examples=[
                OpenApiExample(
                    "Webhooks registered",
                    value={},
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Bad Request - Failed to register webhooks.",
            examples=[
                OpenApiExample(
                    "Registration error",
                    value={"error": "Failed to register webhooks."},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)
