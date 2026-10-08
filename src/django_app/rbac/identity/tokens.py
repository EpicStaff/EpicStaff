import hmac
from dataclasses import dataclass

from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken, Token
from rest_framework_simplejwt.utils import get_md5_hash_password


@dataclass
class TokenPair:
    access: str
    refresh: str

    @classmethod
    def for_user(cls, user) -> "TokenPair":
        """Mint a pair bound to `user`'s current password hash.

        `user` must already carry the password the pair should survive: a
        pair minted from an instance holding the old hash is dead on arrival.
        """
        refresh = RefreshToken.for_user(user)
        return cls(access=str(refresh.access_token), refresh=str(refresh))


def is_bound_to_current_password(token: Token, user) -> bool:
    """Return whether `token` was minted under `user`'s current password.

    The same rule `JWTAuthentication.get_user` applies to access tokens
    (`CHECK_REVOKE_TOKEN`), for the paths that validate a token without going
    through it: the refresh endpoint and token introspection. A token with
    no claim — minted before the setting was enabled — is not bound.
    """
    claim = token.get(api_settings.REVOKE_TOKEN_CLAIM)
    if not isinstance(claim, str):
        return False
    return hmac.compare_digest(claim, get_md5_hash_password(user.password))
