from drf_spectacular.utils import OpenApiResponse, OpenApiExample, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

TWILIO_PHONE_NUMBERS_GET = dict(
    summary="Return the list of incoming phone numbers from Twilio.",
    description="Fetches up to 100 incoming phone numbers associated with the configured Twilio account. "
    "Requires Twilio Account SID and Auth Token to be set in Voice Settings. "
    "Each number includes its SID, phone number, friendly name, and currently configured voice URL.",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="List of incoming phone numbers returned successfully.",
            examples=[
                OpenApiExample(
                    "Phone numbers list",
                    value=[
                        {
                            "sid": "PNxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                            "phone_number": "+15551234567",
                            "friendly_name": "My Twilio Number",
                            "voice_url": "https://example.com/voice",
                        }
                    ],
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Bad Request - Twilio credentials are missing.",
            examples=[
                OpenApiExample(
                    "Missing credentials",
                    value={"error": "Twilio Account SID and Auth Token are required"},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        502: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Bad Gateway - Twilio API request failed.",
            examples=[
                OpenApiExample(
                    "Twilio API error",
                    value={"error": "Unable to reach Twilio API"},
                    response_only=True,
                ),
            ],
        ),
    },
)

TWILIO_CHANNEL_PHONE_NUMBERS_GET = dict(
    summary="Return the list of incoming phone numbers from Twilio for this channel.",
    description="Fetches up to 100 incoming phone numbers for the Twilio account configured on this "
    "`TwilioChannel`. Unlike `TWILIO_PHONE_NUMBERS_GET` (which takes a raw account SID/auth token via "
    "headers and is superadmin-only), this resolves `account_sid` and the auth token server-side from "
    "the channel's stored `Secret` — the raw auth token is never exposed to the client. Any authenticated "
    "member of the channel's own org may call this for their own org's channel (same org scoping as the "
    "rest of `TwilioChannelViewSet`). Each number includes its SID, phone number, friendly name, and "
    "currently configured voice URL.",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="List of incoming phone numbers returned successfully.",
            examples=[
                OpenApiExample(
                    "Phone numbers list",
                    value={
                        "results": [
                            {
                                "sid": "PNxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                                "phone_number": "+15551234567",
                                "friendly_name": "My Twilio Number",
                                "voice_url": "https://example.com/voice",
                            }
                        ]
                    },
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Bad Request - Twilio credentials are not configured on this channel.",
            examples=[
                OpenApiExample(
                    "Missing credentials",
                    value={"error": "No Twilio credentials configured for this channel"},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Not Found - channel does not exist or does not belong to the active org.",
        ),
        502: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Bad Gateway - Twilio API request failed.",
            examples=[
                OpenApiExample(
                    "Twilio API error",
                    value={"error": "Unable to reach Twilio API"},
                    response_only=True,
                ),
            ],
        ),
    },
)

REALTIME_CHANNEL_LOOKUP_BY_TOKEN_GET = dict(
    summary="Resolve a RealtimeChannel by its unique token (internal, API-key only).",
    description="Looks up a RealtimeChannel directly by its unique `token` field, "
    "bypassing org-context scoping. The token is an unguessable UUID that is "
    "itself the authorization/lookup key — used by the `realtime` service to "
    "resolve which agent answers an inbound Twilio call, a request Twilio makes "
    "with no logged-in user and no `X-Organization-Id` header. Restricted to "
    "system API-key-authenticated callers (`IsSystemApiKeyAuthenticated`, "
    "`key_type=SYSTEM` only); a JWT session or a self-issued user API key "
    "cannot use this endpoint.",
    parameters=[
        OpenApiParameter(
            name="token",
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.QUERY,
            required=True,
            description="The RealtimeChannel's unique token.",
        ),
    ],
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Channel found and returned.",
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Bad Request - missing token query param.",
            examples=[
                OpenApiExample(
                    "Missing token",
                    value={"error": "token is required"},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Forbidden - caller is not authenticated with a system API key.",
        ),
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="No channel exists for the given token.",
        ),
    },
)

TWILIO_CONFIGURE_WEBHOOK_POST = dict(
    summary="Set the VoiceUrl on a Twilio phone number to the configured voice stream URL.",
    description="Configures the webhook on the specified Twilio phone number (by SID) to point at the "
    "application's voice stream endpoint. Derives the webhook URL from the configured ngrok tunnel — "
    "the WSS voice stream URL is converted to an HTTPS URL. "
    "Requires Twilio credentials and an active ngrok tunnel to be set up in Voice Settings.",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Webhook URL configured successfully.",
            examples=[
                OpenApiExample(
                    "Webhook configured",
                    value={"webhook_url": "https://example.com/voice"},
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Bad Request - Missing or invalid input.",
            examples=[
                OpenApiExample(
                    "Missing phone_sid",
                    value={"error": "phone_sid is required"},
                    response_only=True,
                ),
                OpenApiExample(
                    "Missing Twilio credentials",
                    value={"error": "Twilio Account SID and Auth Token are required"},
                    response_only=True,
                ),
                OpenApiExample(
                    "No voice stream URL",
                    value={
                        "error": "No voice stream URL configured — set up an ngrok tunnel first"
                    },
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        502: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Bad Gateway - Twilio API request failed.",
            examples=[
                OpenApiExample(
                    "Twilio API error",
                    value={"error": "Unable to reach Twilio API"},
                    response_only=True,
                ),
            ],
        ),
    },
)
