from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status, serializers as drf_serializers
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiResponse

from tables.authentication import JwtOrApiKeyAuthentication
from tables.models.auth_models import ApiKey


_user_credentials_request = inline_serializer(
    name="UserCredentialsRequest",
    fields={
        "username": drf_serializers.CharField(),
        "password": drf_serializers.CharField(),
        "email": drf_serializers.EmailField(required=False),
    },
)

_auth_tokens_response = inline_serializer(
    name="AuthTokensResponse",
    fields={
        "access": drf_serializers.CharField(),
        "refresh": drf_serializers.CharField(),
        "api_key": drf_serializers.CharField(),
    },
)


class AuthMeView(APIView):
    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get current user",
        responses={
            200: inline_serializer(
                name="AuthMeResponse",
                fields={
                    "id": drf_serializers.IntegerField(),
                    "username": drf_serializers.CharField(),
                    "email": drf_serializers.CharField(),
                },
            ),
        },
    )
    def get(self, request):
        user = request.user
        return Response(
            {
                "id": getattr(user, "id", None),
                "username": getattr(user, "username", None),
                "email": getattr(user, "email", None),
            }
        )


class TokenIntrospectView(APIView):
    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Introspect JWT token",
        description="Requires API key authentication. Validates a JWT access token and returns its claims.",
        request=inline_serializer(
            name="TokenIntrospectRequest",
            fields={"token": drf_serializers.CharField()},
        ),
        responses={
            200: inline_serializer(
                name="TokenIntrospectResponse",
                fields={
                    "active": drf_serializers.BooleanField(),
                    "user_id": drf_serializers.IntegerField(required=False),
                    "username": drf_serializers.CharField(required=False),
                    "scopes": drf_serializers.ListField(child=drf_serializers.CharField(), required=False),
                },
            ),
            400: OpenApiResponse(description="token is required"),
            403: OpenApiResponse(description="API key required"),
        },
    )
    def post(self, request):
        if not isinstance(request.user, ApiKey):
            return Response(
                {"detail": "API key required"},
                status=status.HTTP_403_FORBIDDEN,
            )
        token = request.data.get("token")
        if not token:
            return Response(
                {"active": False, "error": "token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            access = AccessToken(token)
        except TokenError:
            return Response({"active": False}, status=status.HTTP_200_OK)

        user_id = access.get("user_id")
        username = access.get("username")
        scopes = access.get("scopes", [])

        return Response(
            {
                "active": True,
                "user_id": user_id,
                "username": username,
                "scopes": scopes,
            },
            status=status.HTTP_200_OK,
        )


class ApiKeyValidateView(APIView):
    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Validate API key",
        description="Requires API key authentication. Returns metadata about the current API key.",
        responses={
            200: inline_serializer(
                name="ApiKeyValidateResponse",
                fields={
                    "active": drf_serializers.BooleanField(),
                    "name": drf_serializers.CharField(),
                    "prefix": drf_serializers.CharField(),
                    "scopes": drf_serializers.ListField(child=drf_serializers.CharField()),
                },
            ),
            403: OpenApiResponse(description="API key required"),
        },
    )
    def get(self, request):
        if not isinstance(request.user, ApiKey):
            return Response(
                {"detail": "API key required"},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(
            {
                "active": True,
                "name": request.user.name,
                "prefix": request.user.prefix,
                "scopes": request.auth.get("scopes", [])
                if isinstance(request.auth, dict)
                else [],
            },
            status=status.HTTP_200_OK,
        )


class SwaggerTokenView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Get JWT token for Swagger UI",
        request=inline_serializer(
            name="SwaggerTokenRequest",
            fields={
                "username": drf_serializers.CharField(),
                "password": drf_serializers.CharField(),
            },
        ),
        responses={
            200: inline_serializer(
                name="SwaggerTokenResponse",
                fields={
                    "access_token": drf_serializers.CharField(),
                    "token_type": drf_serializers.CharField(),
                },
            ),
            401: OpenApiResponse(description="Invalid credentials"),
        },
    )
    def post(self, request):
        serializer = TokenObtainPairSerializer(
            data={
                "username": request.data.get("username"),
                "password": request.data.get("password"),
            }
        )
        if not serializer.is_valid():
            return Response(
                {"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED
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

    @extend_schema(
        summary="Reset user",
        description="Deletes all existing users and API keys, then creates a new superuser and a new 'realtime-default' API key. Requires authentication.",
        request=_user_credentials_request,
        responses={
            201: _auth_tokens_response,
            400: OpenApiResponse(description="username and password are required"),
        },
    )
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        email = request.data.get("email", "")

        if not username or not password:
            return Response(
                {"detail": "username and password are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_model = get_user_model()
        user_model.objects.all().delete()
        ApiKey.objects.all().delete()

        user = user_model.objects.create_superuser(
            username=username, password=password, email=email
        )

        raw_key = ApiKey.generate_raw_key()
        key = ApiKey(name="realtime-default")
        key.set_key(raw_key)
        key.save()

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "api_key": raw_key,
            },
            status=status.HTTP_201_CREATED,
        )


class FirstSetupView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Check if setup is needed",
        responses={
            200: inline_serializer(
                name="FirstSetupStatusResponse",
                fields={"needs_setup": drf_serializers.BooleanField()},
            ),
        },
    )
    def get(self, request):
        user_model = get_user_model()
        needs_setup = not user_model.objects.exists()
        return Response({"needs_setup": needs_setup})

    @extend_schema(
        summary="Perform initial setup",
        description="Creates the first superuser and a default API key. Fails if any user already exists.",
        request=_user_credentials_request,
        responses={
            201: _auth_tokens_response,
            400: OpenApiResponse(description="Setup already completed or missing credentials"),
        },
    )
    def post(self, request):
        user_model = get_user_model()
        if user_model.objects.exists():
            return Response(
                {"detail": "Setup already completed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        username = request.data.get("username")
        password = request.data.get("password")
        email = request.data.get("email", "")

        if not username or not password:
            return Response(
                {"detail": "username and password are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = user_model.objects.create_superuser(
            username=username, password=password, email=email
        )

        raw_key = ApiKey.generate_raw_key()
        key = ApiKey(name="realtime-default")
        key.set_key(raw_key)
        key.save()

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "api_key": raw_key,
            },
            status=status.HTTP_201_CREATED,
        )
