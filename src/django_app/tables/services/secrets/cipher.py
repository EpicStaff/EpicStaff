import base64
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from tables.services.secrets.exceptions import (
    SecretDecryptionError,
    SecretTooLargeError,
)

if TYPE_CHECKING:
    from tables.models import Secret

_HKDF_INFO = b"epicstaff.secrets.v1"
_TAIL_LENGTH = 4
_MIN_LENGTH_FOR_TAIL = 9  # shorter values are fully masked, mirroring SecretCharField
MAX_PLAINTEXT_BYTES = 8192  # sizes Secret.value's max_length — see design doc §4


@dataclass(frozen=True)
class SealedValue:
    ciphertext: str
    tail: str

    def write_to(self, secret: "Secret") -> None:
        """Assign both derived fields together, so no call site sets one and forgets the other."""
        secret.value = self.ciphertext
        secret.tail = self.tail


class SecretCipher:
    """The only place a Secret's plaintext value is sealed or opened.

    The key is HKDF-derived from settings.SECRET_KEY — see the design doc
    for the accepted SECRET_KEY-rotation trade-off.
    """

    @cached_property
    def _fernet(self) -> Fernet:
        if not settings.DEBUG and not settings.SECRET_KEY_IS_EXPLICIT:
            raise ImproperlyConfigured(
                "SECRET_KEY must be set explicitly in the environment: the secrets "
                "encryption key is derived from it. Without it Django generates a "
                "random key per process, so stored secrets would become undecryptable."
            )
        derived = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO
        ).derive(settings.SECRET_KEY.encode())
        return Fernet(base64.urlsafe_b64encode(derived))

    def seal(self, *, plaintext: str) -> SealedValue:
        plaintext_bytes = plaintext.encode()
        if len(plaintext_bytes) > MAX_PLAINTEXT_BYTES:
            raise SecretTooLargeError(
                detail=(
                    f"Secret value is {len(plaintext_bytes)} bytes; the maximum is "
                    f"{MAX_PLAINTEXT_BYTES}."
                )
            )
        ciphertext = self._fernet.encrypt(plaintext_bytes).decode()
        tail = (
            plaintext[-_TAIL_LENGTH:] if len(plaintext) >= _MIN_LENGTH_FOR_TAIL else ""
        )
        return SealedValue(ciphertext=ciphertext, tail=tail)

    def open(self, *, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise SecretDecryptionError() from exc


secret_cipher = SecretCipher()
