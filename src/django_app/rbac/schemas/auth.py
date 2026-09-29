from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

from rbac.serializers.auth import (
    FirstSetupRequestSerializer,
    FirstSetupResponseSerializer,
    FirstSetupStatusSerializer,
    LoginResponseSerializer,
    LogoutResponseSerializer,
    RefreshResponseSerializer,
    ResetUserRequestSerializer,
    ResetUserResponseSerializer,
    SwaggerTokenRequestSerializer,
    SwaggerTokenResponseSerializer,
    TicketResponseSerializer,
    TokenIntrospectRequestSerializer,
    TokenIntrospectResponseSerializer,
)

API_KEY_VALIDATE_GET = {
    "summary": "Validate the current API key",
    "description": (
        "Requires an API key. Returns metadata about the calling key "
        "including the owning user's id (null for env-seeded system keys). "
        "Permissions come from the owning user's live RBAC role, not a "
        "per-key scope list — the response carries no `scopes` field."
    ),
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Key is active.",
            examples=[
                OpenApiExample(
                    "Active key",
                    value={
                        "active": True,
                        "name": "my-key",
                        "prefix": "es-abc12345",
                        "owner_user_id": 3,
                    },
                    response_only=True,
                ),
            ],
        ),
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
}

FIRST_SETUP_GET = {
    "summary": "Check if first-time setup is required",
    "description": (
        "Whether the browser setup flow should be offered. `needs_setup` is "
        "true only when no user exists AND this deployment allows HTTP "
        "first-setup; `setup_mode` reports which creation path is live. "
        "No authentication required. See docs/rbac/first_setup_operations.md."
    ),
    "responses": {200: FirstSetupStatusSerializer},
}

FIRST_SETUP_POST = {
    "summary": "Perform first-time setup",
    "description": (
        "Creates the first superadmin, the default organization, and a "
        "membership with the built-in Superadmin role, then returns JWT "
        "tokens. Available only when this deployment allows HTTP "
        "first-setup. See docs/rbac/first_setup_operations.md."
    ),
    "request": FirstSetupRequestSerializer,
    "responses": {
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
                        "message": "Validation failed",
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
                        "message": "Validation failed",
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
        403: OpenApiResponse(
            response=OpenApiTypes.STR,
            description=(
                "HTTP first-setup is disabled on this deployment (code: first_setup_disabled)."
            ),
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
                        "message": "Setup has already been completed",
                    },
                    response_only=True,
                    status_codes=["409"],
                ),
            ],
        ),
    },
}

TOKEN_INTROSPECT_POST = {
    "summary": "Introspect a JWT access token",
    "description": (
        "Service-to-service JWT validator: the caller authenticates with "
        "an API key and passes a JWT in the body to get its claims back. "
        "Requires a SYSTEM-type API key — user-owned keys are rejected. "
        "Intended for internal services / gateways that should not hold "
        "`JWT_SECRET` but still need to verify bearer tokens. "
        "See `docs/rbac/auth_endpoints.md` for full behavior."
    ),
    "request": TokenIntrospectRequestSerializer,
    "responses": {
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
                        "message": "token: This field is required.",
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Request was not authenticated with a SYSTEM API key.",
            examples=[
                OpenApiExample(
                    "System API key required",
                    value={
                        "detail": "System API key required",
                    },
                    response_only=True,
                    status_codes=["403"],
                ),
            ],
        ),
    },
}

LOGIN_POST = {
    "summary": "Log in and obtain JWT tokens",
    "description": (
        "Accepts `email`, `password`, and optional `remember_me` (bool, default "
        "false). Returns a short-lived access token; the refresh token is set as "
        "an HttpOnly cookie (`auth.refresh`, Path=/api/auth/, SameSite=Lax). "
        "`remember_me=true` -> Max-Age = configured refresh lifetime; "
        "`remember_me=false` -> Max-Age = 30 minutes. The intent is embedded as "
        "a claim so it survives rotation. Wrong credentials return a flat 401. "
        "Throttled to 5 attempts/min per IP+email; the 6th returns 429 with a "
        "`Retry-After` header."
    ),
    "responses": {
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
                        "message": "Validation failed",
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
}

LOGOUT_POST = {
    "summary": "Log out (blacklist refresh token)",
    "description": (
        "Reads the refresh token from the HttpOnly `auth.refresh` cookie, "
        "blacklists it so it can no longer be used to obtain new access "
        "tokens, and clears the cookie. The short-lived access token "
        "continues to work until its own expiry. Ownership is verified — "
        "a leaked refresh token cannot be used to log out a different user. "
        "No request body is required."
    ),
    "responses": {
        205: LogoutResponseSerializer,
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Refresh token is malformed, expired, already blacklisted, or belongs to a different user.",
            examples=[
                OpenApiExample(
                    "Invalid or expired refresh token",
                    value={
                        "status_code": 400,
                        "code": "invalid_or_expired_refresh",
                        "message": "Refresh token is invalid, expired, or already revoked.",
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
}

REFRESH_POST = {
    "summary": "Refresh access token",
    "description": (
        "Reads the refresh token from the HttpOnly `auth.refresh` cookie. "
        "Returns a fresh short-lived access token in the response body. "
        "When token rotation is enabled, the rotated refresh token is set "
        "as a new HttpOnly cookie. No request body is required."
    ),
    "responses": {
        200: RefreshResponseSerializer,
        401: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Refresh cookie missing, token expired, or already blacklisted.",
            examples=[
                OpenApiExample(
                    "No refresh token",
                    value={"detail": "No refresh token."},
                    response_only=True,
                    status_codes=["401"],
                ),
                OpenApiExample(
                    "Token expired",
                    value={"detail": "Token is invalid or expired."},
                    response_only=True,
                    status_codes=["401"],
                ),
            ],
        ),
    },
}

RESET_USER_POST = {
    "summary": "Reset user (destructive)",
    "description": (
        "Deletes all Users inside a single transaction (their API keys "
        "cascade; the system API key survives), then creates a new "
        "superadmin. Organizations are left intact; the new superadmin "
        "is given a default-organization membership (the default org is "
        "reused if one exists, otherwise created)."
    ),
    "request": ResetUserRequestSerializer,
    "responses": {
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
                        "message": "Validation failed",
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
}

SSE_TICKET_POST = {
    "summary": "Issue a short-lived single-use SSE ticket",
    "description": (
        "Issue a single-use SSE ticket bound to the calling JWT user. The ticket "
        "is used as a `?ticket=...` query param on SSE endpoints because "
        "EventSource cannot attach an `Authorization` header. The ticket is consumed "
        "on first read, so reconnects require a fresh ticket."
    ),
    "responses": {
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
}

SWAGGER_TOKEN_POST = {
    "summary": "Swagger UI token endpoint (OAuth2 password flow)",
    "description": (
        "OAuth2 password flow token endpoint for Swagger UI. "
        "Swagger sends `username` + `password`; `username` is interpreted as email "
        "since `USERNAME_FIELD = 'email'` on the custom User model."
    ),
    "request": SwaggerTokenRequestSerializer,
    "responses": {
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
}

WS_TICKET_POST = {
    "summary": "Issue a short-lived single-use WebSocket ticket",
    "description": (
        "Issues a single-use ticket bound to the calling JWT user. The ticket is passed "
        "as a `?ticket=...` query param when opening a WebSocket connection because the "
        "WebSocket handshake cannot carry an `Authorization` header. "
        "The ticket is consumed on first use (Redis GETDEL), so it cannot be replayed — "
        "each reconnect requires a fresh ticket issued by a new call to this endpoint. "
        "TTL is governed by the `GRAPH_WS_TICKET_TTL` setting and is returned "
        "as `expires_in` in the response."
    ),
    "responses": {
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
}
