"""Seal values the way django_app does before it sends them to the sandbox.

The root conftest points the service's settings at TRANSPORT_KEY, so what `seal` produces
opens with the cryptographer the service's dependency provider builds. The sealers here
are built independently of that provider, with the wire contract's HKDF info written out
rather than imported, so a consumer reading the wrong key or the wrong HKDF info fails the
tests instead of round-tripping with itself.
"""

from foundation.cryptographer import FernetRotatedCryptographer

TRANSPORT_KEY = "sandbox-tests-transport-key"
TRANSPORT_HKDF_INFO = b"epicstaff.secrets.transport.v1"

_SEALER = FernetRotatedCryptographer(TRANSPORT_KEY, hkdf_info=TRANSPORT_HKDF_INFO)
_FOREIGN_SEALER = FernetRotatedCryptographer(
    "another-deployment-transport-key", hkdf_info=TRANSPORT_HKDF_INFO
)


def seal(plaintext: str) -> str:
    """Encrypt `plaintext` under the service's transport key."""
    return _SEALER.encrypt(plaintext)


def seal_with_foreign_key(plaintext: str) -> str:
    """Encrypt `plaintext` under a key the service does not hold."""
    return _FOREIGN_SEALER.encrypt(plaintext)
