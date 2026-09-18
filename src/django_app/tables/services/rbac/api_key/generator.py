import hashlib
import secrets
from dataclasses import dataclass


KEY_PREFIX = "es-"
# Chars of the raw key stored/displayed as the key's public identifier.
PREFIX_LENGTH = 12


@dataclass(frozen=True)
class GeneratedKey:
    raw_key: str
    prefix: str
    key_hash: str


class ApiKeyGenerator:
    """The only place that knows what a raw EpicStaff API key looks like.

    Plain SHA-256 (no HMAC pepper): the raw key carries 256 bits of entropy,
    so hashing is sufficient and key validity stays decoupled from Django
    SECRET_KEY rotation.
    """

    @staticmethod
    def generate() -> GeneratedKey:
        raw_key = KEY_PREFIX + secrets.token_urlsafe(32)
        return GeneratedKey(
            raw_key=raw_key,
            prefix=ApiKeyGenerator.prefix_of(raw_key),
            key_hash=ApiKeyGenerator.hash_key(raw_key),
        )

    @staticmethod
    def hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode()).hexdigest()

    @staticmethod
    def prefix_of(raw_key: str) -> str:
        return raw_key[:PREFIX_LENGTH]
