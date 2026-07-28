import base64
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

from tables.services.secrets.exceptions import (
    SecretDecryptionError,
    SecretTooLargeError,
)

if TYPE_CHECKING:
    from tables.models import Secret

_HKDF_INFO = b"epicstaff.secrets.v1"
_TAIL_LENGTH = 4
_MIN_LENGTH_FOR_TAIL = 9  # shorter values are fully masked, mirroring SecretCharField
MAX_TEXT_BYTES = 8192  # sizes Secret.value's max_length — see design doc §4


@dataclass(frozen=True)
class SealedValue:
    encryptedtext: str
    tail: str

    def write_to(self, secret: "Secret") -> None:
        """Assign both derived fields together, so no call site sets one and forgets the other."""
        secret.value = self.encryptedtext
        secret.tail = self.tail


class SecretEncryption:
    """The only place a Secret's text value is encrypted or decrypted.

    The key is HKDF-derived from settings.SECRET_KEY — see the design doc
    for the accepted SECRET_KEY-rotation trade-off.
    """

    @cached_property
    def _fernet(self) -> Fernet:
        derived = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO
        ).derive(settings.SECRET_KEY.encode())
        return Fernet(base64.urlsafe_b64encode(derived))

    def encrypt(self, *, text: str) -> SealedValue:
        text_bytes = text.encode()
        if len(text_bytes) > MAX_TEXT_BYTES:
            raise SecretTooLargeError(
                detail=(
                    f"Secret value is {len(text_bytes)} bytes; the maximum is "
                    f"{MAX_TEXT_BYTES}."
                )
            )
        encryptedtext = self._fernet.encrypt(text_bytes).decode()
        tail = text[-_TAIL_LENGTH:] if len(text) >= _MIN_LENGTH_FOR_TAIL else ""
        return SealedValue(encryptedtext=encryptedtext, tail=tail)

    def decrypt(self, *, encryptedtext: str) -> str:
        try:
            return self._fernet.decrypt(encryptedtext.encode()).decode()
        except InvalidToken as exc:
            raise SecretDecryptionError() from exc


secret_encryption = SecretEncryption()
