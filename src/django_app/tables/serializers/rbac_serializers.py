from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


# ---- First-setup ----


class FirstSetupStatusSerializer(serializers.Serializer):
    needs_setup = serializers.BooleanField()


class FirstSetupRequestSerializer(serializers.Serializer):
    # Schema-only: request validation is performed by
    # `AuthValidationService.validate_first_setup` so errors can be
    # aggregated and formatted uniformly.
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class _SetupUserPayload(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    display_name = serializers.CharField(allow_null=True)
    is_superadmin = serializers.BooleanField()


class _SetupOrganizationPayload(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_active = serializers.BooleanField()


class FirstSetupResponseSerializer(serializers.Serializer):
    user = _SetupUserPayload()
    organization = _SetupOrganizationPayload()
    access = serializers.CharField()
    refresh = serializers.CharField()


# ---- Token introspect ----


class TokenIntrospectRequestSerializer(serializers.Serializer):
    token = serializers.CharField()


class TokenIntrospectResponseSerializer(serializers.Serializer):
    active = serializers.BooleanField()
    user_id = serializers.IntegerField(required=False)
    email = serializers.EmailField(required=False)
    scopes = serializers.ListField(child=serializers.CharField(), required=False)


# ---- API-key validate ----


class ApiKeyValidateResponseSerializer(serializers.Serializer):
    active = serializers.BooleanField()
    name = serializers.CharField()
    prefix = serializers.CharField()
    scopes = serializers.ListField(child=serializers.CharField())
    owner_user_id = serializers.IntegerField(allow_null=True)


# ---- Reset user ----


class ResetUserRequestSerializer(serializers.Serializer):
    # Schema-only: request validation is performed by
    # `AuthValidationService.validate_reset_user`.
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class ResetUserResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    api_key = serializers.CharField()


# ---- Logout ----


class LogoutRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField(write_only=True)


class LogoutResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


# ---- Ticket ----
class TicketResponseSerializer(serializers.Serializer):
    ticket = serializers.CharField()
    expires_in = serializers.IntegerField()


# ---- Swagger token (OAuth2 password flow) ----


class SwaggerTokenRequestSerializer(serializers.Serializer):
    # OAuth2 password flow convention uses `username`; we interpret it as email.
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class SwaggerTokenResponseSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    token_type = serializers.CharField()


# ---- Password recovery ----


class PasswordResetRequestSerializer(serializers.Serializer):
    # Schema-only: real validation in
    # `AuthValidationService.validate_password_reset_request`.
    email = serializers.EmailField()


class PasswordResetRequestResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    smtp_configured = serializers.BooleanField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    # Schema-only: real validation in
    # `AuthValidationService.validate_password_reset_confirm`.
    token = serializers.UUIDField()
    new_password = serializers.CharField(write_only=True)


class PasswordResetConfirmResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


class AdminPasswordResetSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)
    new_password = serializers.CharField(write_only=True)


# ---- Custom TokenObtainPair (embeds email + is_superadmin claims) ----


class LoginSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["is_superadmin"] = user.is_superadmin
        return token


class LoginResponseSerializer(serializers.Serializer):
    refresh = serializers.CharField()
    access = serializers.CharField()
