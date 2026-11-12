from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from django.conf import settings
from foundation.cryptographer import DecryptDataError, FernetRotatedCryptographer
from tables.services.secrets.exceptions import (
    SecretDecryptionError,
    SecretTooLargeError,
)

if TYPE_CHECKING:
    from tables.models import Secret

_HKDF_INFO = b"epicstaff.secrets.at-rest.v2"
_TAIL_LENGTH = 4
_MIN_LENGTH_FOR_TAIL = 9  # shorter values are fully masked, mirroring SecretCharField
MAX_TEXT_BYTES = 8192  # sizes Secret.value's max_length - see design doc section 4


@dataclass(frozen=True)
class SealedValue:
    encryptedtext: str
    tail: str

    def write_to(self, secret: "Secret") -> None:
        """Assign both derived fields together, so no call site sets one and forgets the other."""
        secret.value = self.encryptedtext
        secret.tail = self.tail


class SecretEncryption:
    """The only place a Secret's text value is encrypted or decrypted."""

    @cached_property
    def _cryptographer(self) -> FernetRotatedCryptographer:
        """Encrypts with SECRETS_ENCRYPTION_KEY; also decrypts SECRETS_ENCRYPTION_PREVIOUS_KEYS."""
        return FernetRotatedCryptographer(
            settings.SECRETS_ENCRYPTION_KEY,
            settings.SECRETS_ENCRYPTION_PREVIOUS_KEYS,
            hkdf_info=_HKDF_INFO,
            max_data_size=MAX_TEXT_BYTES,
        )

    def encrypt(self, *, text: str) -> SealedValue:
        text_bytes = text.encode()
        if len(text_bytes) > MAX_TEXT_BYTES:
            raise SecretTooLargeError(
                detail=(
                    f"Secret value is {len(text_bytes)} bytes; the maximum is {MAX_TEXT_BYTES}."
                )
            )
        encryptedtext = self._cryptographer.encrypt(text)
        tail = text[-_TAIL_LENGTH:] if len(text) >= _MIN_LENGTH_FOR_TAIL else ""
        return SealedValue(encryptedtext=encryptedtext, tail=tail)

    def decrypt(self, *, encryptedtext: str) -> str:
        try:
            return self._cryptographer.decrypt(encryptedtext)
        except DecryptDataError as exc:
            raise SecretDecryptionError() from exc


secret_encryption = SecretEncryption()
