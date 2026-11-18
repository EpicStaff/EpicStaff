"""Seal values the way django_app does, and build the agent's cryptographer for the same key.

The sealer spells out django_app's HKDF info instead of reading the agent's setting, so
an agent setting that drifts from the wire contract fails the tests.
"""

import settings
from foundation.cryptographer import FernetRotatedCryptographer

TRANSPORT_KEY = "agent-tests-transport-key"

# The SECRETS_TRANSPORT_HKDF_INFO value django_app, the producer, seals with.
_PRODUCER_HKDF_INFO = b"epicstaff.secrets.transport.v1"

_SEALER = FernetRotatedCryptographer(TRANSPORT_KEY, hkdf_info=_PRODUCER_HKDF_INFO)
_FOREIGN_SEALER = FernetRotatedCryptographer(
    "another-deployment-transport-key", hkdf_info=_PRODUCER_HKDF_INFO
)


def agent_cryptographer() -> FernetRotatedCryptographer:
    """Build the cryptographer main() builds, for TRANSPORT_KEY and no previous keys."""
    return FernetRotatedCryptographer(
        TRANSPORT_KEY, hkdf_info=settings.SECRETS_TRANSPORT_HKDF_INFO.encode()
    )


def seal(plaintext: str) -> str:
    """Encrypt `plaintext` under the agent's transport key."""
    return _SEALER.encrypt(plaintext)


def seal_with_foreign_key(plaintext: str) -> str:
    """Encrypt `plaintext` under a key the agent does not hold."""
    return _FOREIGN_SEALER.encrypt(plaintext)


def header_marker(ciphertext: str) -> str:
    """Wrap a ciphertext in the header secret marker django_app sends."""
    return f"epicstaff_secret({ciphertext})"
