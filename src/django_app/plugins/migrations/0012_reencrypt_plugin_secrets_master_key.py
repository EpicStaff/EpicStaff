"""Re-encrypt the plugin secrets from the SECRET_KEY-derived key to SECRETS_ENCRYPTION_KEY.

The columns: PluginSettingValue.encrypted_value (null for a plain setting),
PluginDatabase.app_password_encrypted and PluginSigningKey.private_key_encrypted.

Idempotent: a value the target main key already reads is skipped, and a value under one of
SECRETS_ENCRYPTION_PREVIOUS_KEYS moves to the main key. A value no key reads is left as it
is and its pk is logged. Reverting re-encrypts back to the SECRET_KEY-derived key.

The key derivations are copied here rather than imported: a migration must keep doing what
it did when it was written, whatever the app code turns into later.
"""

from django.conf import settings
from django.db import migrations
from foundation.cryptographer import DecryptDataError, FernetRotatedCryptographer
from loguru import logger

LEGACY_HKDF_INFO = b"epicstaff.secrets.v1"
MASTER_KEY_HKDF_INFO = b"epicstaff.secrets.at-rest.v2"
MAX_TEXT_BYTES = 8192
BATCH_SIZE = 500

ENCRYPTED_COLUMNS = (
    ("PluginSettingValue", "encrypted_value"),
    ("PluginDatabase", "app_password_encrypted"),
    ("PluginSigningKey", "private_key_encrypted"),
)


def _legacy_cryptographer():
    return FernetRotatedCryptographer(
        settings.SECRET_KEY, hkdf_info=LEGACY_HKDF_INFO, max_data_size=MAX_TEXT_BYTES
    )


def _master_key_cryptographer():
    return FernetRotatedCryptographer(
        settings.SECRETS_ENCRYPTION_KEY,
        settings.SECRETS_ENCRYPTION_PREVIOUS_KEYS,
        hkdf_info=MASTER_KEY_HKDF_INFO,
        max_data_size=MAX_TEXT_BYTES,
    )


def _reencrypt_column(model, field_name, source, target):
    """Re-encrypt every non-empty value of `field_name` under the main key of `target`."""
    rows = (
        model._base_manager.exclude(**{f"{field_name}__isnull": True})
        .exclude(**{field_name: ""})
        .only("pk", field_name)
    )
    changed = []
    unreadable_pks = []
    for row in rows.iterator(chunk_size=BATCH_SIZE):
        value = getattr(row, field_name)
        if target.is_rotated(value):
            continue
        try:
            text = source.decrypt(value)
        except DecryptDataError:
            # Sealed under one of the target's other keys: still readable, so rotate it.
            try:
                text = target.decrypt(value)
            except DecryptDataError:
                unreadable_pks.append(row.pk)
                continue
        setattr(row, field_name, target.encrypt(text))
        changed.append(row)
        if len(changed) == BATCH_SIZE:
            model._base_manager.bulk_update(changed, [field_name])
            changed.clear()
    model._base_manager.bulk_update(changed, [field_name])
    if unreadable_pks:
        logger.warning(
            "{}.{}: left {} value(s) untouched, no key decrypts them; pks: {}",
            model._meta.label,
            field_name,
            len(unreadable_pks),
            unreadable_pks,
        )


def _reencrypt_columns(apps, source, target):
    for model_name, field_name in ENCRYPTED_COLUMNS:
        _reencrypt_column(apps.get_model("plugins", model_name), field_name, source, target)


def encrypt_with_master_key(apps, schema_editor):
    _reencrypt_columns(apps, source=_legacy_cryptographer(), target=_master_key_cryptographer())


def encrypt_with_secret_key(apps, schema_editor):
    _reencrypt_columns(apps, source=_master_key_cryptographer(), target=_legacy_cryptographer())


class Migration(migrations.Migration):
    dependencies = [
        ("plugins", "0011_package_navigation_icons"),
    ]

    operations = [
        migrations.RunPython(encrypt_with_master_key, encrypt_with_secret_key),
    ]
