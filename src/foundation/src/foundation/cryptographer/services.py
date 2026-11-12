import itertools
from base64 import urlsafe_b64encode
from collections.abc import Iterable
from typing import TYPE_CHECKING

from foundation.utils import humanize
from foundation.utils.lazy import LazyImport

if TYPE_CHECKING:
    from cryptography import fernet
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
else:
    fernet = LazyImport("cryptography.fernet")
    Fernet = LazyImport("cryptography.fernet", "Fernet")
    SHA256 = LazyImport("cryptography.hazmat.primitives.hashes", "SHA256")
    HKDF = LazyImport("cryptography.hazmat.primitives.kdf.hkdf", "HKDF")

from .base import AbstractRotatedCryptographer
from .errors import (
    DecodeDataError,
    DecryptDataError,
    EncodeDataError,
    EncryptDataError,
    RotateDataError,
)

__all__ = ["FernetRotatedCryptographer"]


class FernetRotatedCryptographer(AbstractRotatedCryptographer):
    MAX_DATA_SIZE: int = humanize.to_byte_size("8kb")
    HKDF_INFO: bytes | None = None

    def __init__(
        self,
        main_key: str,
        other_keys: Iterable[str] = (),
        hkdf_info: bytes | None = None,
        max_data_size: int | None = None,
    ):
        self._max_data_size = self.MAX_DATA_SIZE if max_data_size is None else max_data_size
        self._hkdf_info = self.HKDF_INFO if hkdf_info is None else hkdf_info
        self._fernets: list[Fernet] = [
            self._build_fernet(key, self._build_hkdf(self._hkdf_info))
            for key in itertools.chain((main_key,), other_keys)
        ]

        self._multi_fernet = fernet.MultiFernet(self._fernets)

    def encrypt(self, data: str) -> str:
        encoded = self._encode(data)
        if len(encoded) > self._max_data_size:
            raise EncryptDataError(
                f"Data is too large. Max data size is {self._max_data_size} bytes."
            )
        encrypted = self._multi_fernet.encrypt(encoded)
        decoded = self._decode(encrypted)
        return decoded

    def decrypt(self, data: str) -> str:
        encoded = self._encode(data)
        try:
            decrypted = self._multi_fernet.decrypt(encoded)
        except fernet.InvalidToken as e:
            raise DecryptDataError("Data cannot be decrypted.") from e
        decoded = self._decode(decrypted)
        return decoded

    def rotate(self, data: str) -> str:
        encoded = self._encode(data)
        try:
            rotated = self._multi_fernet.rotate(encoded)
        except fernet.InvalidToken as e:
            raise RotateDataError("Data cannot be rotated.") from e
        decoded = self._decode(rotated)
        return decoded

    def is_rotated(self, data: str) -> bool:
        encoded = self._encode(data)
        main_fernet = self._fernets[0]
        try:
            main_fernet.decrypt(encoded)
        except fernet.InvalidToken:
            return False
        return True

    def _build_fernet(self, key: str, hkdf: HKDF) -> Fernet:
        byte_key = key.encode()
        derived_key = hkdf.derive(byte_key)
        base64_key = urlsafe_b64encode(derived_key)
        return Fernet(base64_key)

    def _build_hkdf(self, info: bytes | None):
        return HKDF(algorithm=SHA256(), length=32, salt=None, info=info)

    def _encode(self, data: str) -> bytes:
        try:
            return data.encode()
        except UnicodeEncodeError as e:
            raise EncodeDataError("Data is not encodable as UTF-8.") from e

    def _decode(self, data: bytes) -> str:
        try:
            return data.decode()
        except UnicodeDecodeError as e:
            raise DecodeDataError("Data is not decodable as UTF-8.") from e
