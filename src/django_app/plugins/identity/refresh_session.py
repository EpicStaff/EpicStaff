"""The person EpicStaff's refresh cookie signs in, for the plugin authorize endpoint."""

from django.contrib.auth import get_user_model
from rbac.identity.tokens import is_bound_to_current_password
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken


def user_for_refresh_token(refresh_token: str | None):
    """Return the user a refresh token signs in, or None when it signs in nobody.

    The checks of `/api/auth/refresh/`: signature, expiry, token type and blacklist (simplejwt's
    `RefreshToken`), the user exists and may log in (`USER_AUTHENTICATION_RULE`, which checks
    `is_active`), and the token was minted under the user's current password. Unlike the
    refresh endpoint it neither rotates nor blacklists the token: the authorize endpoint only
    reads the session, and leaves the cookie as it is.
    """
    if not refresh_token:
        return None
    try:
        token = RefreshToken(refresh_token)
    except TokenError:
        return None
    user_id = token.get(api_settings.USER_ID_CLAIM)
    if user_id is None:
        return None
    user = get_user_model().objects.filter(**{api_settings.USER_ID_FIELD: user_id}).first()
    if not api_settings.USER_AUTHENTICATION_RULE(user):
        return None
    if not is_bound_to_current_password(token, user):
        return None
    return user
