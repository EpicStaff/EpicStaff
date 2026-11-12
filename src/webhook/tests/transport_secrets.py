"""Seal values the way django_app does before it sends them to the webhook service.

The root conftest points the service's settings at TRANSPORT_KEY, so what `seal` produces
opens with the cryptographer `create_app` builds. The sealers here are built independently
of the app, with the wire contract's HKDF info written out rather than imported, so an app
reading the wrong key or the wrong HKDF info fails the route tests instead of
round-tripping with itself.
"""

from foundation.cryptographer import AbstractCryptographer, FernetRotatedCryptographer

TRANSPORT_KEY = "webhook-tests-transport-key"
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


def sealing_cryptographer() -> AbstractCryptographer:
    """The cryptographer to hand a tunnel or registry built directly: it opens what `seal` makes."""
    return _SEALER
