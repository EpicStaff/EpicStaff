import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from tables.models import Secret
from tables.services.secrets import (
    MAX_PLAINTEXT_BYTES,
    SealedValue,
    SecretCipher,
    SecretDecryptionError,
    SecretTooLargeError,
    secret_cipher,
)


def test_open_seal_roundtrip_ascii():
    sealed = secret_cipher.seal(plaintext="sk-live-abc123")
    assert secret_cipher.open(ciphertext=sealed.ciphertext) == "sk-live-abc123"


def test_open_seal_roundtrip_unicode():
    plaintext = "pässwörd-日本語-🔑"
    sealed = secret_cipher.seal(plaintext=plaintext)
    assert secret_cipher.open(ciphertext=sealed.ciphertext) == plaintext


def test_seal_is_not_deterministic():
    first = secret_cipher.seal(plaintext="same-value")
    second = secret_cipher.seal(plaintext="same-value")
    assert first.ciphertext != second.ciphertext
    assert secret_cipher.open(ciphertext=first.ciphertext) == "same-value"
    assert secret_cipher.open(ciphertext=second.ciphertext) == "same-value"


def test_ciphertext_does_not_contain_plaintext():
    plaintext = "super-secret-token-value"
    sealed = secret_cipher.seal(plaintext=plaintext)
    assert plaintext not in sealed.ciphertext


def test_open_rejects_tampered_ciphertext():
    sealed = secret_cipher.seal(plaintext="tamper-me")
    tampered = list(sealed.ciphertext)
    middle = len(tampered) // 2
    tampered[middle] = "A" if tampered[middle] != "A" else "B"
    with pytest.raises(SecretDecryptionError):
        secret_cipher.open(ciphertext="".join(tampered))


def test_seal_at_max_plaintext_fits_column():
    plaintext = "a" * MAX_PLAINTEXT_BYTES
    sealed = secret_cipher.seal(plaintext=plaintext)
    max_length = Secret._meta.get_field("value").max_length
    assert len(sealed.ciphertext) <= max_length


def test_seal_above_max_plaintext_raises():
    plaintext = "a" * (MAX_PLAINTEXT_BYTES + 1)
    with pytest.raises(SecretTooLargeError):
        secret_cipher.seal(plaintext=plaintext)


def test_tail_populated_above_threshold():
    sealed = secret_cipher.seal(plaintext="123456789")  # 9 chars
    assert sealed.tail == "6789"


def test_tail_empty_at_threshold_boundary():
    sealed = secret_cipher.seal(plaintext="12345678")  # 8 chars
    assert sealed.tail == ""


def test_sealed_value_write_to_sets_both_fields():
    secret = Secret(name="TEMP", org=None)
    sealed = SealedValue(ciphertext="dummy-ciphertext", tail="beef")
    sealed.write_to(secret)
    assert secret.value == "dummy-ciphertext"
    assert secret.tail == "beef"


@override_settings(DEBUG=False, SECRET_KEY_IS_EXPLICIT=False)
def test_fernet_raises_when_secret_key_not_explicit():
    # A fresh instance, not the module singleton — cached_property would
    # otherwise hand back a Fernet cached before override_settings applied.
    fresh_cipher = SecretCipher()
    with pytest.raises(ImproperlyConfigured):
        fresh_cipher.seal(plaintext="anything")
