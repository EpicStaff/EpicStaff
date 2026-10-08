from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.settings import api_settings
from tables.models.user import DISPLAY_NAME_MAX_LENGTH

from rbac.identity.tokens import is_bound_to_current_password

# ---- First-setup ----


class FirstSetupStatusSerializer(serializers.Serializer):
    needs_setup = serializers.BooleanField()
    setup_mode = serializers.CharField()


class FirstSetupRequestSerializer(serializers.Serializer):
    # Schema-only: request validation is performed by
    # `AuthValidationService.validate_first_setup` so errors can be
    # aggregated and formatted uniformly.
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    display_name = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=DISPLAY_NAME_MAX_LENGTH,
        help_text="Trimmed. Omit or send null to derive it from the email.",
    )


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


# ---- Token introspect ----


class TokenIntrospectRequestSerializer(serializers.Serializer):
    token = serializers.CharField()


class TokenIntrospectResponseSerializer(serializers.Serializer):
    active = serializers.BooleanField()
    user_id = serializers.IntegerField(required=False)
    email = serializers.EmailField(required=False)
    scopes = serializers.ListField(child=serializers.CharField(), required=False)
    org_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Org ids the token's user is a member of. Used by internal "
        "services (e.g. realtime) to verify the caller owns a given resource's org.",
    )
    is_superadmin = serializers.BooleanField(required=False)


# ---- Reset user ----


class ResetUserRequestSerializer(serializers.Serializer):
    # Schema-only: request validation is performed by
    # `AuthValidationService.validate_reset_user`.
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    display_name = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=DISPLAY_NAME_MAX_LENGTH,
        help_text="Trimmed. Omit or send null to derive it from the email.",
    )


class ResetUserResponseSerializer(serializers.Serializer):
    access = serializers.CharField()


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
    detail = serializers.CharField(
        help_text=(
            "Human-readable outcome, the same for every email. With SMTP: a "
            "link has been sent if the email is registered. Without SMTP: reset "
            "by email is unavailable, ask an administrator."
        )
    )
    smtp_configured = serializers.BooleanField(
        help_text=(
            "False when the server has no SMTP relay: self-service reset is "
            "disabled and nothing was sent. Same value for every email."
        )
    )


class PasswordResetConfirmSerializer(serializers.Serializer):
    # Schema-only: real validation in
    # `AuthValidationService.validate_password_reset_confirm`.
    token = serializers.CharField(write_only=True)
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


class PasswordBoundTokenRefreshSerializer(TokenRefreshSerializer):
    """Refresh serializer that also rejects tokens from a previous password.

    simplejwt's refresh serializer does not apply `CHECK_REVOKE_TOKEN`, so
    without this a refresh token outlives the password it was minted under.
    Rejections raise `TokenError`, the same signal as an expired or
    malformed token, so the view answers 401 and clears the cookie.
    """

    def validate(self, attrs):
        # simplejwt 5.4.0 offers no hook between its decode and its user
        # lookup, so the token is decoded here and again in super().validate().
        refresh = self.token_class(attrs["refresh"])
        user_id = refresh.get(api_settings.USER_ID_CLAIM)
        user = (
            get_user_model().objects.filter(**{api_settings.USER_ID_FIELD: user_id}).first()
            if user_id is not None
            else None
        )
        if user is None or not is_bound_to_current_password(refresh, user):
            raise TokenError("Token is not bound to the user's current password.")
        return super().validate(attrs)


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()


class RefreshResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
