from drf_spectacular.utils import OpenApiResponse, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from tables.serializers.rbac_serializers import (
    ApiKeyValidateResponseSerializer,
    FirstSetupStatusSerializer,
    FirstSetupRequestSerializer,
    FirstSetupResponseSerializer,
    LoginResponseSerializer,
    LogoutRequestSerializer,
    LogoutResponseSerializer,
    ResetUserRequestSerializer,
    ResetUserResponseSerializer,
    TicketResponseSerializer,
    SwaggerTokenRequestSerializer,
    SwaggerTokenResponseSerializer,
    TokenIntrospectRequestSerializer,
    TokenIntrospectResponseSerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

API_KEY_VALIDATE_GET = dict(
    summary="Validate the current API key",
    description=(
        "Requires an API key. Returns metadata about the calling key "
        "including the owning user's id (null for env-seeded system keys)."
    ),
    responses={
        200: ApiKeyValidateResponseSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Authentication credentials were not provided",
            examples=[
                OpenApiExample(
                    "API key missing",
                    value={"detail": "API key required"},
                    response_only=True,
                ),
            ],
        ),
    },
)

FIRST_SETUP_GET = dict(
    summary="Check if first-time setup is required",
    description=(
        "Returns whether the application still needs its initial setup. "
        "Responds with `needs_setup: true` if no User row exists in the "
        "database, or `needs_setup: false` if at least one user is present. "
        "No authentication is required. The frontend uses this to decide "
        "whether to redirect to the setup wizard before showing the login page."
    ),
    responses={200: FirstSetupStatusSerializer},
)

FIRST_SETUP_POST = dict(
    summary="Perform first-time setup",
    description=(
        "Creates the first superadmin (is_superadmin=True), a default "
        "Organization (name from `DEFAULT_ORGANIZATION_NAME` env var, "
        "falling back to 'Default Organization'), and an OrganizationUser "
        "membership with the built-in 'Org Admin' role. Returns the user, "
        "the org, and JWT tokens so the frontend can drop the user straight "
        "into the app. Refuses with 409 if any user already exists or if "
        "the default organization row survived a prior user wipe."
    ),
    request=FirstSetupRequestSerializer,
    responses={
        201: FirstSetupResponseSerializer,
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Validation error — one or more fields failed validation.",
            examples=[
                OpenApiExample(
                    "Missing fields",
                    value={
                        "status_code": 400,
                        "code": "invalid",
                        "message": "FormValidationError: Validation failed",
                        "errors": [
                            {
                                "field": "email",
                                "value": None,
                                "reason": "This field is required.",
                            },
                            {
                                "field": "password",
                                "value": "***",
                                "reason": "This field is required.",
                            },
                        ],
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
                OpenApiExample(
                    "Invalid email / weak password",
                    value={
                        "status_code": 400,
                        "code": "invalid",
                        "message": "FormValidationError: Validation failed",
                        "errors": [
                            {
                                "field": "email",
                                "value": "not-an-email",
                                "reason": "Enter a valid email address.",
                            },
                            {
                                "field": "password",
                                "value": "***",
                                "reason": "This password is too short. It must contain at least 8 characters.",
                            },
                        ],
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        409: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Setup already completed — at least one user already exists.",
            examples=[
                OpenApiExample(
                    "Setup already completed",
                    value={
                        "status_code": 409,
                        "code": "setup_already_completed",
                        "message": "SetupAlreadyCompletedError: Setup has already been completed",
                    },
                    response_only=True,
                    status_codes=["409"],
                ),
            ],
        ),
    },
)

TOKEN_INTROSPECT_POST = dict(
    summary="Introspect a JWT access token",
    description=(
        "Service-to-service JWT validator: the caller authenticates with "
        "an API key and passes a JWT in the body to get its claims back. "
        "Intended for internal services / gateways that should not hold "
        "`JWT_SECRET` but still need to verify bearer tokens. "
        "See `docs/rbac/auth_endpoints.md` for full behavior."
    ),
    request=TokenIntrospectRequestSerializer,
    responses={
        200: TokenIntrospectResponseSerializer,
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Validation error — `token` field is missing or blank.",
            examples=[
                OpenApiExample(
                    "Missing token field",
                    value={
                        "status_code": 400,
                        "code": "invalid",
                        "message": "ValidationError: {'token': [ErrorDetail(string='This field is required.', code='required')]}",
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Request was not authenticated with an API key.",
            examples=[
                OpenApiExample(
                    "API key required",
                    value={
                        "detail": "API key required",
                    },
                    response_only=True,
                    status_codes=["403"],
                ),
            ],
        ),
    },
)

LOGIN_POST = dict(
    summary="Log in and obtain JWT tokens",
    description=(
        "Accepts `email` and `password`. Validates both fields are present "
        "and non-blank before delegating to simplejwt. Returns a refresh token "
        "and a short-lived access token. Wrong-credential errors are returned "
        "as a flat 401 (no per-field detail) to avoid user-enumeration leaks. "
        "Throttled to 5 attempts per minute per IP+email combination; the 6th "
        "attempt returns 429 with a `Retry-After` header."
    ),
    responses={
        200: LoginResponseSerializer,
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Validation error — `email` or `password` field is missing or blank.",
            examples=[
                OpenApiExample(
                    "Missing fields",
                    value={
                        "status_code": 400,
                        "code": "invalid",
                        "message": "FormValidationError: Validation failed",
                        "errors": [
                            {
                                "field": "email",
                                "value": None,
                                "reason": "This field is required.",
                            },
                            {
                                "field": "password",
                                "value": "***",
                                "reason": "This field is required.",
                            },
                        ],
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        429: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Too many login attempts — throttle limit exceeded.",
        ),
    },
)

LOGOUT_POST = dict(
    summary="Log out (blacklist refresh token)",
    description=(
        "Blacklists the caller's refresh token so it can no longer be used "
        "to obtain new access tokens. The short-lived access token continues "
        "to work until its own expiry. Ownership is verified — a leaked "
        "refresh token cannot be used to log out a different user."
    ),
    request=LogoutRequestSerializer,
    responses={
        205: LogoutResponseSerializer,
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Refresh token is missing, malformed, expired, already blacklisted, or belongs to a different user.",
            examples=[
                OpenApiExample(
                    "Invalid or expired refresh token",
                    value={
                        "status_code": 400,
                        "code": "invalid_or_expired_refresh",
                        "message": "InvalidRefreshTokenError: Refresh token is invalid, expired, or already revoked.",
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)

RESET_USER_POST = dict(
    summary="Reset user (destructive)",
    description=(
        "Deletes all Users and ApiKeys inside a single transaction, then "
        "creates a new superadmin and a fresh 'realtime-default' API key. "
        "Organizations are left intact; the new superadmin has no "
        "automatic membership and relies on the is_superadmin bypass."
    ),
    request=ResetUserRequestSerializer,
    responses={
        201: ResetUserResponseSerializer,
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Validation error — one or more fields failed validation.",
            examples=[
                OpenApiExample(
                    "Missing fields",
                    value={
                        "status_code": 400,
                        "code": "invalid",
                        "message": "FormValidationError: Validation failed",
                        "errors": [
                            {
                                "field": "email",
                                "value": None,
                                "reason": "This field is required.",
                            },
                            {
                                "field": "password",
                                "value": "***",
                                "reason": "This field is required.",
                            },
                        ],
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)

SSE_TICKET_POST = dict(
    summary="Issue a short-lived single-use SSE ticket",
    description=(
        "Issue a single-use SSE ticket bound to the calling JWT user. The ticket "
        "is used as a `?ticket=...` query param on SSE endpoints because "
        "EventSource cannot attach an `Authorization` header. The ticket is consumed "
        "on first read, so reconnects require a fresh ticket."
    ),
    responses={
        200: TicketResponseSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Caller authenticated via an API key that has no owning user.",
            examples=[
                OpenApiExample(
                    "No user context",
                    value={"detail": "This endpoint requires a user context."},
                    response_only=True,
                    status_codes=["403"],
                ),
            ],
        ),
    },
)

SWAGGER_TOKEN_POST = dict(
    summary="Swagger UI token endpoint (OAuth2 password flow)",
    description=(
        "OAuth2 password flow token endpoint for Swagger UI. "
        "Swagger sends `username` + `password`; `username` is interpreted as email "
        "since `USERNAME_FIELD = 'email'` on the custom User model."
    ),
    request=SwaggerTokenRequestSerializer,
    responses={
        200: SwaggerTokenResponseSerializer,
        401: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Invalid credentials — username/password combination is wrong.",
            examples=[
                OpenApiExample(
                    "Invalid credentials",
                    value={"error": "Invalid credentials"},
                    response_only=True,
                    status_codes=["401"],
                ),
            ],
        ),
        403: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Authentication failed.",
            examples=[
                OpenApiExample(
                    "Authentication failed",
                    value={
                        "status_code": 403,
                        "code": "authentication_failed",
                        "message": "AuthenticationFailed: No active account found with the given credentials",
                    },
                    response_only=True,
                    status_codes=["403"],
                ),
            ],
        ),
    },
)

WS_TICKET_POST = dict(
    summary="Issue a short-lived single-use WebSocket ticket",
    description=(
        "Issues a single-use ticket bound to the calling JWT user. The ticket is passed "
        "as a `?ticket=...` query param when opening a WebSocket connection because the "
        "WebSocket handshake cannot carry an `Authorization` header. "
        "The ticket is consumed on first use (Redis GETDEL), so it cannot be replayed — "
        "each reconnect requires a fresh ticket issued by a new call to this endpoint. "
        "TTL is governed by the `GRAPH_WS_TICKET_TTL_SECONDS` setting and is returned "
        "as `expires_in` in the response."
    ),
    responses={
        200: OpenApiResponse(
            response=TicketResponseSerializer,
            description="Ticket issued successfully.",
            examples=[
                OpenApiExample(
                    "Ticket issued",
                    value={
                        "ticket": "kPx3mN8vQzR1uYwT6aJcXdLsEoFbHgIi",
                        "expires_in": 30,
                    },
                    response_only=True,
                    status_codes=["200"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Caller authenticated via an API key that has no owning user.",
            examples=[
                OpenApiExample(
                    "No user context",
                    value={"detail": "This endpoint requires a user context."},
                    response_only=True,
                    status_codes=["403"],
                ),
            ],
        ),
    },
)
