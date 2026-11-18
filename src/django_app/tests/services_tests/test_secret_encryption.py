import pytest
from tables.models import Secret
from tables.services.secrets import (
    MAX_TEXT_BYTES,
    SealedValue,
    SecretDecryptionError,
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


def test_encrypt_above_max_text_is_refused_by_its_encoded_size():
    # 4097 characters, 8194 bytes: the limit counts bytes.
    with pytest.raises(SecretTooLargeError) as raised:
        secret_encryption.encrypt(text="\u00e9" * 4097)

    assert str(raised.value.detail) == "Secret value is 8194 bytes; the maximum is 8192."


@pytest.mark.parametrize(
    ("text", "tail"),
    [
        ("123456789", "6789"),
        ("12345678", ""),
        ("", ""),
    ],
)
def test_tail_shows_the_last_four_characters_from_nine_on(text, tail):
    assert secret_encryption.encrypt(text=text).tail == tail


def test_sealed_value_write_to_sets_both_fields():
    secret = Secret(name="TEMP", org=None)
    sealed = SealedValue(encryptedtext="dummy-encryptedtext", tail="beef")
    sealed.write_to(secret)
    assert secret.value == "dummy-encryptedtext"
    assert secret.tail == "beef"
