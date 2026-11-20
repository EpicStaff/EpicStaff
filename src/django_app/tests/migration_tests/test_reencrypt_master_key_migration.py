"""tables 0291 and plugins 0012 re-encrypt the stored secrets from the SECRET_KEY-derived key
to SECRETS_ENCRYPTION_KEY.

Invariants: every legacy value in Secret.value, SessionCallback.encrypted_secret,
PluginSettingValue.encrypted_value, PluginDatabase.app_password_encrypted and
PluginSigningKey.private_key_encrypted becomes readable by SecretEncryption; a value already
under the main key keeps its exact bytes; a value under a previous key moves to the main key;
a value no key reads is left as it is and only its pk is logged; null and empty values stay
as they are. Reverting brings the legacy format back.
"""

import base64

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings
from loguru import logger
from plugins.models import (
    Plugin,
    PluginDatabase,
    PluginDatabaseServer,
    PluginSettingValue,
    PluginSigningKey,
    PluginState,
)
from rbac.models import Organization
from tables.models import Secret, Session, SessionCallback
from tables.services.secrets import SecretEncryption

BEFORE = [
    ("tables", "0290_systemoneconfig_openai_provider"),
    ("plugins", "0011_package_navigation_icons"),
]
AFTER = [
    ("tables", "0291_reencrypt_secrets_master_key"),
    ("plugins", "0012_reencrypt_plugin_secrets_master_key"),
]

MAIN_KEY = "main-master-key-for-tests"
PREVIOUS_KEY = "previous-master-key-for-tests"
UNREADABLE = "not-a-fernet-token"
# (model, key in the _create_rows result, column, the text its legacy value encrypts)
LEGACY_COLUMNS = [
    ("Secret", "legacy_secret", "value", "sk-legacy"),
    ("SessionCallback", "pending_callback", "encrypted_secret", "hmac-secret"),
    ("PluginSettingValue", "setting", "encrypted_value", "token"),
    ("PluginDatabase", "database", "app_password_encrypted", "db-password"),
    ("PluginSigningKey", "signing_key", "private_key_encrypted", "private-seed"),
]
APP_LABELS = {
    "Secret": "tables",
    "SessionCallback": "tables",
    "PluginSettingValue": "plugins",
    "PluginDatabase": "plugins",
    "PluginSigningKey": "plugins",
}


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _migrate_to_leaves():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def _legacy_fernet() -> Fernet:
    """The SECRET_KEY-derived key SecretEncryption used before the master key."""
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"epicstaff.secrets.v1"
    ).derive(settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(derived))


def _encrypt_in_legacy_format(text: str) -> str:
    return _legacy_fernet().encrypt(text.encode()).decode()


def _create_rows():
    """One legacy value in each encrypted column, plus the rows the edge cases need."""
    organization = Organization.objects.create(name="reencrypt-org")
    plugin = Plugin.objects.create(
        identifier="weather", name="Weather", description="Forecasts.", state=PluginState.RUNNING
    )
    server = PluginDatabaseServer.objects.create(name="plugins_db", host="plugins_db", port=5432)

    def make_secret(name, value):
        return Secret.objects.create(org=organization, name=name, value=value).pk

    def make_callback(status, encrypted_secret):
        session = Session.objects.create(status=Session.SessionStatus.END)
        return SessionCallback.objects.create(
            session=session,
            url="http://chat:8000/cb",
            status=status,
            encrypted_secret=encrypted_secret,
        ).pk

    return {
        "organization": organization.pk,
        "legacy_secret": make_secret("LEGACY", _encrypt_in_legacy_format("sk-legacy")),
        "unreadable_secret": make_secret("UNREADABLE", UNREADABLE),
        "pending_callback": make_callback(
            SessionCallback.Status.PENDING, _encrypt_in_legacy_format("hmac-secret")
        ),
        "delivered_callback": make_callback(SessionCallback.Status.DELIVERED, ""),
        "setting": PluginSettingValue.objects.create(
            plugin=plugin, key="api_token", encrypted_value=_encrypt_in_legacy_format("token")
        ).pk,
        "plain_setting": PluginSettingValue.objects.create(
            plugin=plugin, key="units", value="metric"
        ).pk,
        "database": PluginDatabase.objects.create(
            plugin=plugin,
            server=server,
            installation_id="installation-1",
            database_name="plugin_weather",
            owner_role="plugin_weather_owner",
            app_role="plugin_weather_app",
            job_role="plugin_weather_job",
            app_password_encrypted=_encrypt_in_legacy_format("db-password"),
        ).pk,
        "signing_key": PluginSigningKey.objects.create(
            kid="kid-1",
            private_key_encrypted=_encrypt_in_legacy_format("private-seed"),
            public_key="p" * 43,
        ).pk,
        "empty_signing_key": PluginSigningKey.objects.create(
            kid="kid-2", private_key_encrypted="", public_key="q" * 43
        ).pk,
    }


def _column(apps, model_name, pk, field_name):
    model = apps.get_model(APP_LABELS[model_name], model_name)
    return getattr(model._base_manager.get(pk=pk), field_name)


@pytest.mark.django_db(transaction=True)
@override_settings(
    SECRETS_ENCRYPTION_KEY=MAIN_KEY, SECRETS_ENCRYPTION_PREVIOUS_KEYS=(PREVIOUS_KEY,)
)
def test_forward_reencrypts_legacy_values_and_leaves_the_rest():
    encryption = SecretEncryption()
    messages = []
    try:
        pks = _create_rows()
        old_apps = _migrate(BEFORE)
        # Created once the reverse has run, so they start out in the new format.
        old_secret_model = old_apps.get_model("tables", "Secret")
        already_new = encryption.encrypt(text="sk-new").encryptedtext
        pks["already_new_secret"] = old_secret_model._base_manager.create(
            org_id=pks["organization"], name="ALREADY_NEW", value=already_new
        ).pk
        with override_settings(SECRETS_ENCRYPTION_KEY=PREVIOUS_KEY):
            under_previous_key = SecretEncryption().encrypt(text="sk-previous").encryptedtext
        pks["previous_key_secret"] = old_secret_model._base_manager.create(
            org_id=pks["organization"], name="PREVIOUS_KEY", value=under_previous_key
        ).pk

        sink_id = logger.add(messages.append, level="WARNING", format="{message}")
        try:
            new_apps = _migrate(AFTER)
        finally:
            logger.remove(sink_id)

        for model_name, pk_name, field_name, text in LEGACY_COLUMNS:
            migrated = _column(new_apps, model_name, pks[pk_name], field_name)
            assert encryption.decrypt(encryptedtext=migrated) == text
        assert _column(new_apps, "Secret", pks["already_new_secret"], "value") == already_new
        rotated = _column(new_apps, "Secret", pks["previous_key_secret"], "value")
        with override_settings(SECRETS_ENCRYPTION_PREVIOUS_KEYS=()):
            assert SecretEncryption().decrypt(encryptedtext=rotated) == "sk-previous"
        assert _column(new_apps, "Secret", pks["unreadable_secret"], "value") == UNREADABLE
        delivered = _column(
            new_apps, "SessionCallback", pks["delivered_callback"], "encrypted_secret"
        )
        assert delivered == ""
        plain = _column(new_apps, "PluginSettingValue", pks["plain_setting"], "encrypted_value")
        assert plain is None
        empty = _column(
            new_apps, "PluginSigningKey", pks["empty_signing_key"], "private_key_encrypted"
        )
        assert empty == ""

        # Only the unreadable row is reported, by pk: not the rotated one, never a value.
        warnings = [str(message) for message in messages]
        column_warnings = [
            warning
            for warning in warnings
            if any(
                f"{model_name}.{field_name}" in warning
                for model_name, _, field_name, _ in LEGACY_COLUMNS
            )
        ]
        assert len(column_warnings) == 1
        assert "Secret.value" in column_warnings[0]
        assert f"[{pks['unreadable_secret']}]" in column_warnings[0]
        assert not [warning for warning in warnings if UNREADABLE in warning]
    finally:
        _migrate_to_leaves()


@pytest.mark.django_db(transaction=True)
def test_reverse_restores_the_legacy_format():
    try:
        pks = _create_rows()
        _migrate(BEFORE)
        _migrate(AFTER)

        old_apps = _migrate(BEFORE)

        for model_name, pk_name, field_name, text in LEGACY_COLUMNS:
            reverted = _column(old_apps, model_name, pks[pk_name], field_name)
            assert _legacy_fernet().decrypt(reverted.encode()).decode() == text
        assert _column(old_apps, "Secret", pks["unreadable_secret"], "value") == UNREADABLE
    finally:
        _migrate_to_leaves()
