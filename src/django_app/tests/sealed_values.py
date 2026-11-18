"""Open the secret values django_app seals for transport, the way a receiving service does."""

import re

from django.conf import settings
from foundation.cryptographer import FernetRotatedCryptographer

# The consumers' own copy of the marker syntax, independent of django_app's.
SECRET_MARKER_RE = re.compile(r"epicstaff_secret\(\s*([^)]+?)\s*\)")


def consumer_cryptographer() -> FernetRotatedCryptographer:
    """Return a cryptographer holding the transport key the consumers of django_app hold."""
    return FernetRotatedCryptographer(
        settings.SECRETS_TRANSPORT_KEY, hkdf_info=settings.SECRETS_TRANSPORT_HKDF_INFO.encode()
    )


def open_sealed(value: str) -> str:
    """Return the plaintext of one transport-sealed value."""
    return consumer_cryptographer().decrypt(value)


def open_sealed_values(values: dict[str, str]) -> dict[str, str]:
    """Return `values` with every transport-sealed value opened."""
    return {name: open_sealed(value) for name, value in values.items()}


def open_sealed_headers(headers: dict | None) -> dict | None:
    """Return `headers` with every `epicstaff_secret(<ciphertext>)` marker opened to plaintext.

    Non-empty headers without any marker fail: they left django_app in plaintext.
    """
    if headers:
        assert any(
            isinstance(value, str) and SECRET_MARKER_RE.search(value) for value in headers.values()
        ), "no sealed marker: headers left django_app in plaintext"
    else:
        return headers

    cryptographer = consumer_cryptographer()
    return {
        key: (
            SECRET_MARKER_RE.sub(lambda match: cryptographer.decrypt(match.group(1)), value)
            if isinstance(value, str)
            else value
        )
        for key, value in headers.items()
    }
