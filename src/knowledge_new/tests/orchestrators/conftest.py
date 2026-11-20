import settings
from foundation.cryptographer import FernetRotatedCryptographer

TRANSPORT_KEY = "knowledge-transport-test-key"

# Built apart from the service's cryptographer, with django_app's literal HKDF info, so a
# drift in the service's setting fails these tests.
_SEALER = FernetRotatedCryptographer(TRANSPORT_KEY, hkdf_info=b"epicstaff.secrets.transport.v1")

# Stands in for the cryptographer bootstrap/di.py injects into the orchestrators.
CRYPTOGRAPHER = FernetRotatedCryptographer(
    TRANSPORT_KEY, hkdf_info=settings.SECRETS_TRANSPORT_HKDF_INFO.encode()
)


def seal(value: str) -> str:
    """Encrypt `value` the way django_app seals a secret for transport."""
    return _SEALER.encrypt(value)


def sealed_marker(value: str) -> str:
    """Return the `epicstaff_secret(<ciphertext>)` header marker for `value`."""
    return f"epicstaff_secret({seal(value)})"
