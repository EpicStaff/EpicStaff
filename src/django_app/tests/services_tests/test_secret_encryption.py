import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from tables.models import Secret
from tables.services.secrets import (
    MAX_TEXT_BYTES,
    SealedValue,
    SecretDecryptionError,
    SecretEncryption,
    SecretTooLargeError,
    secret_encryption,
)


def test_decrypt_encrypt_roundtrip_ascii():
    sealed = secret_encryption.encrypt(text="sk-live-abc123")
    assert (
        secret_encryption.decrypt(encryptedtext=sealed.encryptedtext)
        == "sk-live-abc123"
    )


def test_decrypt_encrypt_roundtrip_unicode():
    text = "pässwörd-日本語-🔑"
    sealed = secret_encryption.encrypt(text=text)
    assert secret_encryption.decrypt(encryptedtext=sealed.encryptedtext) == text


def test_encrypt_is_not_deterministic():
    first = secret_encryption.encrypt(text="same-value")
    second = secret_encryption.encrypt(text="same-value")
    assert first.encryptedtext != second.encryptedtext
    assert secret_encryption.decrypt(encryptedtext=first.encryptedtext) == "same-value"
    assert secret_encryption.decrypt(encryptedtext=second.encryptedtext) == "same-value"


def test_encryptedtext_does_not_contain_text():
    text = "super-secret-token-value"
    sealed = secret_encryption.encrypt(text=text)
    assert text not in sealed.encryptedtext


def test_decrypt_rejects_tampered_encryptedtext():
    sealed = secret_encryption.encrypt(text="tamper-me")
    tampered = list(sealed.encryptedtext)
    middle = len(tampered) // 2
    tampered[middle] = "A" if tampered[middle] != "A" else "B"
    with pytest.raises(SecretDecryptionError):
        secret_encryption.decrypt(encryptedtext="".join(tampered))


def test_encrypt_at_max_text_fits_column():
    text = "a" * MAX_TEXT_BYTES
    sealed = secret_encryption.encrypt(text=text)
    max_length = Secret._meta.get_field("value").max_length
    assert len(sealed.encryptedtext) <= max_length


def test_encrypt_above_max_text_raises():
    text = "a" * (MAX_TEXT_BYTES + 1)
    with pytest.raises(SecretTooLargeError):
        secret_encryption.encrypt(text=text)


def test_tail_populated_above_threshold():
    sealed = secret_encryption.encrypt(text="123456789")  # 9 chars
    assert sealed.tail == "6789"


def test_tail_empty_at_threshold_boundary():
    sealed = secret_encryption.encrypt(text="12345678")  # 8 chars
    assert sealed.tail == ""


def test_sealed_value_write_to_sets_both_fields():
    secret = Secret(name="TEMP", org=None)
    sealed = SealedValue(encryptedtext="dummy-encryptedtext", tail="beef")
    sealed.write_to(secret)
    assert secret.value == "dummy-encryptedtext"
    assert secret.tail == "beef"


@override_settings(SECRET_KEY=None)
def test_encrypt_raises_when_secret_key_is_unset():
    # A fresh instance, not the module singleton — cached_property would
    # otherwise hand back a Fernet cached before override_settings applied.
    # Django's own settings machinery rejects an empty SECRET_KEY before our
    # code ever touches it (LazySettings.__getattr__ special-cases it).
    fresh_encryption = SecretEncryption()
    with pytest.raises(ImproperlyConfigured):
        fresh_encryption.encrypt(text="anything")
