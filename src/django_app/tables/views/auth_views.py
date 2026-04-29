from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from tables.services.rbac.authentication import JwtOrApiKeyAuthentication
from tables.models.rbac_models import ApiKey
from tables.serializers.rbac_serializers import (
    ApiKeyValidateResponseSerializer,
    AuthMeResponseSerializer,
    LoginSerializer,
    LogoutRequestSerializer,
    LogoutResponseSerializer,
    FirstSetupRequestSerializer,
    FirstSetupResponseSerializer,
    FirstSetupStatusSerializer,
    ResetUserRequestSerializer,
    ResetUserResponseSerializer,
    SseTicketResponseSerializer,
    SwaggerTokenRequestSerializer,
    SwaggerTokenResponseSerializer,
    TokenIntrospectRequestSerializer,
    TokenIntrospectResponseSerializer,
)
from tables.services.rbac.auth_service import AuthService, TokenPair
from tables.services.rbac.auth_validation_service import AuthValidationService
from tables.services.rbac.first_setup_service import FirstSetupService
from tables.services.rbac.rbac_exceptions import InvalidRefreshTokenError
from tables.services.rbac.reset_user_service import ResetUserService
from tables.services.rbac.sse_ticket_service import SseTicketService
from tables.throttles import LoginThrottle


class LoginView(TokenObtainPairView):
    """JWT login — accepts `{"email", "password"}` (USERNAME_FIELD=email).

    Throttled by `LoginThrottle` (composite IP|email bucket; rate driven by
    `LOGIN_THROTTLE_RATE` env var, default 5/min). 6th attempt inside the
    window returns 429 with a `Retry-After` header.
    """

    serializer_class = LoginSerializer
    throttle_classes = [LoginThrottle]

    _validator = AuthValidationService()

    def post(self, request, *args, **kwargs):
        # Shape-check both fields and aggregate missing/blank errors
        # before delegating to simplejwt. Wrong-credential errors stay a
        # flat 401 to avoid user-enumeration leaks.
        self._validator.validate_login(request.data)
        return super().post(request, *args, **kwargs)


class LogoutView(APIView):
    """
    JWT logout — blacklists the caller's refresh token so it can no longer
    be used (or rotated) to obtain new access tokens. The short-lived access
    token continues to work until its own expiry.
    """

    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Log out (blacklist refresh token)",
        request=LogoutRequestSerializer,
        responses={
            205: LogoutResponseSerializer,
            400: OpenApiResponse(description="Refresh token invalid or expired"),
        },
    )
    def post(self, request):
        serializer = LogoutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data["refresh"])
            # Ownership check: a leaked refresh token must not let a third
            # party log the owner out. Mismatch is reported with the same
            # exception as malformed/expired tokens so the caller cannot
            # distinguish "real but not yours" from "garbage".
            token_user_id = token.payload.get("user_id")
            if token_user_id is None or int(token_user_id) != request.user.id:
                raise InvalidRefreshTokenError()
            token.blacklist()
        except TokenError as exc:
            raise InvalidRefreshTokenError() from exc
        return Response(
            {"detail": "Logged out."},
            status=status.HTTP_205_RESET_CONTENT,
        )


class SseTicketView(APIView):
    """
    Issue a single-use SSE ticket bound to the calling JWT user. The ticket
    is used as a `?ticket=...` query param on SSE endpoints because
    EventSource cannot attach an `Authorization` header. See
    `docs/rbac/sse_auth.md` for the FE flow.
    """

    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _service = SseTicketService()

    @extend_schema(
        summary="Issue a short-lived single-use SSE ticket",
        responses={200: SseTicketResponseSerializer},
    )
    def post(self, request):
        if not getattr(request.user, "is_authenticated", False) or not hasattr(
            request.user, "email"
        ):
            return Response(
                {"detail": "This endpoint requires a user context."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ticket, ttl = self._service.issue(request.user)
        return Response({"ticket": ticket, "expires_in": ttl})


class FirstSetupView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    _service = FirstSetupService()
    _validator = AuthValidationService()

    @extend_schema(
        summary="Check if first-time setup is required",
        responses={200: FirstSetupStatusSerializer},
    )
    def get(self, request):
        return Response({"needs_setup": self._service.is_setup_required()})

    @extend_schema(
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
            400: OpenApiResponse(description="Validation error"),
            409: OpenApiResponse(description="Setup already completed"),
        },
    )
    def post(self, request):
        cleaned = self._validator.validate_first_setup(request.data)

        result = self._service.setup(
            email=cleaned["email"],
            password=cleaned["password"],
        )
        tokens = TokenPair.for_user(result.user)

        return Response(
            {
                "user": {
                    "id": result.user.id,
                    "email": result.user.email,
                    "display_name": result.user.display_name,
                    "is_superadmin": result.user.is_superadmin,
                },
                "organization": {
                    "id": result.organization.id,
                    "name": result.organization.name,
                    "is_active": result.organization.is_active,
                },
                "access": tokens.access,
                "refresh": tokens.refresh,
            },
            status=status.HTTP_201_CREATED,
        )


class AuthMeView(APIView):
    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _service = AuthService()

    @extend_schema(
        summary="Get current user",
        description=(
            "Returns the authenticated user's profile and list of org "
            "memberships (each with the role). Active-org resolution from "
            "`X-Organization-Id` is added in Story 7."
        ),
        responses={200: AuthMeResponseSerializer},
    )
    def get(self, request):
        if not getattr(request.user, "is_authenticated", False) or not hasattr(
            request.user, "email"
        ):
            # API keys with no `created_by` resolve to AnonymousUser.
            return Response(
                {"detail": "This endpoint requires a user context."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(self._service.build_me_payload(request.user, request=request))


class TokenIntrospectView(APIView):
    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
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
            400: OpenApiResponse(description="token is required"),
            403: OpenApiResponse(description="API key required"),
        },
    )
    def post(self, request):
        if not isinstance(request.auth, ApiKey):
            return Response(
                {"detail": "API key required"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = TokenIntrospectRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]

        try:
            access = AccessToken(token)
        except TokenError:
            return Response({"active": False}, status=status.HTTP_200_OK)

        return Response(
            {
                "active": True,
                "user_id": access.get("user_id"),
                "email": access.get("email"),
                "scopes": access.get("scopes", []),
            },
            status=status.HTTP_200_OK,
        )


class ApiKeyValidateView(APIView):
    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Validate the current API key",
        description=(
            "Requires an API key. Returns metadata about the calling key "
            "including the owning user's id (null for env-seeded system keys)."
        ),
        responses={
            200: ApiKeyValidateResponseSerializer,
            403: OpenApiResponse(description="API key required"),
        },
    )
    def get(self, request):
        key = request.auth
        if not isinstance(key, ApiKey):
            return Response(
                {"detail": "API key required"},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(
            {
                "active": True,
                "name": key.name,
                "prefix": key.prefix,
                "scopes": key.scopes or [],
                "owner_user_id": key.created_by_id,
            },
            status=status.HTTP_200_OK,
        )


class SwaggerTokenView(APIView):
    """
    OAuth2 password flow token endpoint for Swagger UI.
    Swagger sends `username` + `password`; we interpret `username` as email
    (since `USERNAME_FIELD = "email"` on the custom User model).
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginThrottle]

    @extend_schema(
        summary="Swagger UI token endpoint (OAuth2 password flow)",
        request=SwaggerTokenRequestSerializer,
        responses={
            200: SwaggerTokenResponseSerializer,
            401: OpenApiResponse(description="Invalid credentials"),
        },
    )
    def post(self, request):
        serializer = LoginSerializer(
            data={
                "email": request.data.get("username"),
                "password": request.data.get("password"),
            }
        )
        if not serializer.is_valid():
            return Response(
                {"error": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response(
            {
                "access_token": serializer.validated_data["access"],
                "token_type": "bearer",
            }
        )


class ResetUserView(APIView):
    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _service = ResetUserService()
    _validator = AuthValidationService()

    @extend_schema(
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
            400: OpenApiResponse(description="Validation error"),
        },
    )
    def post(self, request):
        cleaned = self._validator.validate_reset_user(request.data)

        user, raw_key = self._service.reset(
            email=cleaned["email"],
            password=cleaned["password"],
        )
        tokens = TokenPair.for_user(user)

        return Response(
            {
                "access": tokens.access,
                "refresh": tokens.refresh,
                "api_key": raw_key,
            },
            status=status.HTTP_201_CREATED,
        )
