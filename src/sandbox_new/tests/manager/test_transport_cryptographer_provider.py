"""The cryptographer the service builds for transport-sealed secrets.

It opens what django_app seals with the transport key and the wire contract's HKDF info,
and still opens what was sealed under a key listed as previous after a rotation.
"""

import pytest
from foundation.cryptographer import DecryptDataError, FernetRotatedCryptographer

from manager import settings
from manager.bootstrap import di as manager_di

from tests.transport_secrets import TRANSPORT_HKDF_INFO, seal, seal_with_foreign_key

PREVIOUS_KEY = "sandbox-tests-previous-transport-key"


def test_it_opens_what_the_producer_seals():
    assert manager_di.cryptographer().decrypt(seal("sk-live-plaintext")) == "sk-live-plaintext"


def test_it_opens_what_was_sealed_under_a_previous_key(monkeypatch):
    monkeypatch.setattr(settings, "SECRETS_TRANSPORT_PREVIOUS_KEYS", [PREVIOUS_KEY])
    old_sealer = FernetRotatedCryptographer(PREVIOUS_KEY, hkdf_info=TRANSPORT_HKDF_INFO)

    opened = manager_di.cryptographer().decrypt(old_sealer.encrypt("sk-live-plaintext"))

    assert opened == "sk-live-plaintext"


def test_it_does_not_open_what_another_key_sealed():
    with pytest.raises(DecryptDataError):
        manager_di.cryptographer().decrypt(seal_with_foreign_key("sk-live-plaintext"))
