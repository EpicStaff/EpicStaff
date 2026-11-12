"""SecretEncryption decrypts under the keys in SECRETS_ENCRYPTION_PREVIOUS_KEYS, refuses any
other key, and no longer reads the SECRET_KEY-derived format.

Settings are overridden per test, so each one builds a fresh SecretEncryption: the module
singleton keeps the cryptographer it built first.
"""

import base64

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.test import override_settings
from tables.services.secrets import SecretDecryptionError, SecretEncryption

OLD_MASTER_KEY = "old-master-key-for-tests"
NEW_MASTER_KEY = "new-master-key-for-tests"


def _encrypt_in_legacy_format(text: str) -> str:
    """What SecretEncryption wrote before the master key: a Fernet keyed off SECRET_KEY."""
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"epicstaff.secrets.v1"
    ).derive(settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(derived)).encrypt(text.encode()).decode()


def test_value_encrypted_under_a_previous_key_still_decrypts():
    with override_settings(SECRETS_ENCRYPTION_KEY=OLD_MASTER_KEY):
        encryptedtext = SecretEncryption().encrypt(text="sk-before-rotation").encryptedtext

    with override_settings(
        SECRETS_ENCRYPTION_KEY=NEW_MASTER_KEY, SECRETS_ENCRYPTION_PREVIOUS_KEYS=(OLD_MASTER_KEY,)
    ):
        assert SecretEncryption().decrypt(encryptedtext=encryptedtext) == "sk-before-rotation"


def test_value_encrypted_under_an_unlisted_key_does_not_decrypt():
    with override_settings(SECRETS_ENCRYPTION_KEY=OLD_MASTER_KEY):
        encryptedtext = SecretEncryption().encrypt(text="sk-before-rotation").encryptedtext

    with (
        override_settings(
            SECRETS_ENCRYPTION_KEY=NEW_MASTER_KEY, SECRETS_ENCRYPTION_PREVIOUS_KEYS=()
        ),
        pytest.raises(SecretDecryptionError),
    ):
        SecretEncryption().decrypt(encryptedtext=encryptedtext)


def test_value_in_the_legacy_secret_key_format_does_not_decrypt():
    encryptedtext = _encrypt_in_legacy_format("sk-legacy")

    with pytest.raises(SecretDecryptionError):
        SecretEncryption().decrypt(encryptedtext=encryptedtext)
