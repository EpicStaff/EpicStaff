from dataclasses import dataclass

from rest_framework_simplejwt.tokens import RefreshToken


@dataclass
class TokenPair:
    access: str
    refresh: str

    @classmethod
    def for_user(cls, user) -> "TokenPair":
        refresh = RefreshToken.for_user(user)
        return cls(access=str(refresh.access_token), refresh=str(refresh))
