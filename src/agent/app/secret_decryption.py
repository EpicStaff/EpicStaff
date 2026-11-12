"""Decryption of the secret values django_app seals with the transport key.

The transport key opens values only while they travel from django_app to this service; the
values stored in the database are sealed under django_app's own at-rest key, with a
different HKDF info, so a copied key cannot cross from one domain into the other.
"""

import re

from foundation.cryptographer import AbstractCryptographer

# Wire contract with django_app's tables/services/secrets/secret_resolver.py (the producer): keep byte-identical.
SECRET_MARKER_RE = re.compile(r"epicstaff_secret\(\s*([^)]+?)\s*\)")


def decrypt_header_markers(
    headers: dict | None, cryptographer: AbstractCryptographer
) -> dict | None:
    """Return `headers` with `epicstaff_secret(<ciphertext>)` markers replaced by plaintext.

    Returns a new dict; the input is never modified. None and an empty dict are returned
    as is, and non-str values are kept unchanged.

    Raises:
        DecryptDataError: A marker holds a value the cryptographer cannot decrypt.
    """
    if not headers:
        return headers

    return {
        key: (
            SECRET_MARKER_RE.sub(lambda match: cryptographer.decrypt(match.group(1)), value)
            if isinstance(value, str)
            else value
        )
        for key, value in headers.items()
    }
