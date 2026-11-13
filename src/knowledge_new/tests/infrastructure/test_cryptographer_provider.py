import settings
from bootstrap import di
from foundation.cryptographer import FernetRotatedCryptographer

_WIRE_HKDF_INFO = b"epicstaff.secrets.transport.v1"


def _sealed(value: str, key: str) -> str:
    return FernetRotatedCryptographer(key, hkdf_info=_WIRE_HKDF_INFO).encrypt(value)


def test_provided_cryptographer_opens_secrets_sealed_with_the_current_or_a_previous_key(
    monkeypatch,
):
    monkeypatch.setattr(settings, "SECRETS_TRANSPORT_KEY", "current-transport-key")
    monkeypatch.setattr(settings, "SECRETS_TRANSPORT_PREVIOUS_KEYS", ["previous-transport-key"])

    cryptographer = di.cryptographer()

    assert cryptographer.decrypt(_sealed("sk-current", "current-transport-key")) == "sk-current"
    assert cryptographer.decrypt(_sealed("sk-previous", "previous-transport-key")) == "sk-previous"
