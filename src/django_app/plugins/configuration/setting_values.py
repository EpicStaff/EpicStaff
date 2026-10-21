"""A plugin's settings: the values the SuperAdmin sets for the settings its manifest declares.

Settings are deployment-wide, one value per plugin and key. Secrets are encrypted at rest and
decrypted in one place only, for the runtime file the plugin's node fetches
(`runtime_settings`); the admin API shows a secret by its last characters at most.
"""

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from django.db import transaction
from django.db.models import F
from epicstaff_plugin.contracts.manifest import PluginManifest, Setting
from epicstaff_plugin.problems import Problem
from tables.services.secrets import MAX_TEXT_BYTES, secret_encryption

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_setting_changes
from plugins.exceptions import InvalidPluginSettingsError
from plugins.models import Plugin, PluginPlacement, PluginSettingValue

SECRET_TYPE = "secret"
MAX_STRING_LENGTH = 1000
MAX_TEXT_LENGTH = 10_000
MAX_URL_LENGTH = 2000
MAX_SECRET_LENGTH = 4096
# The integers a JavaScript number holds exactly, so the Settings form shows what is stored.
MAX_INTEGER_MAGNITUDE = 2**53
BLOCKED_BY_MISSING_SETTINGS = "required_settings_missing"


@dataclass(frozen=True)
class SettingState:
    """One manifest setting with its stored value, if any."""

    setting: Setting
    stored: PluginSettingValue | None


@dataclass(frozen=True)
class PluginSettings:
    states: list[SettingState]
    missing_required: list[str]


def missing_required_settings(manifest: PluginManifest, stored_keys: Iterable[str]) -> list[str]:
    """Return the keys of required settings that have neither a stored value nor a default."""
    stored = set(stored_keys)
    return [
        setting.key
        for setting in manifest.settings
        if setting.required and setting.default is None and setting.key not in stored
    ]


def blocked_reason(manifest: PluginManifest, stored_keys: Iterable[str]) -> str | None:
    """Why the plugin's process must stay stopped, or None: a required setting is missing."""
    return BLOCKED_BY_MISSING_SETTINGS if missing_required_settings(manifest, stored_keys) else None


def runtime_settings(
    manifest: PluginManifest, stored: Iterable[PluginSettingValue]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return `(settings, secret_settings)` as the plugin's runtime file holds them.

    `settings` has every non-secret setting with its stored value or its default (an unset
    optional setting without a default is left out); `secret_settings` has the decrypted
    value of every secret that is set. The only place a setting secret is decrypted.
    """
    by_key = {row.key: row for row in stored}
    settings: dict[str, Any] = {}
    secrets: dict[str, str] = {}
    for setting in manifest.settings:
        row = by_key.get(setting.key)
        if setting.type == SECRET_TYPE:
            if row is not None:
                secrets[setting.key] = secret_encryption.decrypt(encryptedtext=row.encrypted_value)
        elif row is not None:
            settings[setting.key] = row.value
        elif setting.default is not None:
            settings[setting.key] = setting.default
    return settings, secrets


class PluginSettingsService:
    """Reads and changes a plugin's setting values."""

    def settings_of(self, plugin: Plugin, manifest: PluginManifest) -> PluginSettings:
        stored = {row.key: row for row in plugin.setting_values.select_related("updated_by").all()}
        return PluginSettings(
            states=[
                SettingState(setting, stored.get(setting.key)) for setting in manifest.settings
            ],
            missing_required=missing_required_settings(manifest, stored),
        )

    def update(
        self, plugin: Plugin, manifest: PluginManifest, values: dict[str, Any], actor
    ) -> PluginSettings:
        """Set or clear (`None`) the settings named in `values`; others keep their value.

        Any change raises the placement's `settings_revision`, which makes the node restart
        the plugin's process with the new values. A plain value equal to the stored one is no
        change; a secret is never compared (it is not decrypted here), so writing one always
        is. Only the changed keys are logged.

        Raises:
            InvalidPluginSettingsError: An unknown key, a value of the wrong type or size, or
                clearing a required setting that has no default; each located at
                `values.<key>`.
        """
        declared = {setting.key: setting for setting in manifest.settings}
        problems = [
            Problem(f"values.{key}", message)
            for key, value in values.items()
            if (message := _value_problem(declared.get(key), value))
        ]
        if problems:
            raise InvalidPluginSettingsError(problems)
        with transaction.atomic():
            placement = PluginPlacement.objects.select_for_update().filter(plugin=plugin).first()
            stored = {row.key: row for row in plugin.setting_values.select_for_update()}
            changed = [
                key
                for key, value in values.items()
                if _apply(plugin, declared[key], stored.get(key), value, actor)
            ]
            if changed and placement is not None:
                placement.settings_revision = F("settings_revision") + 1
                placement.save(update_fields=["settings_revision", "updated_at"])
            if changed:
                ActivityRecorder().settings_changed(actor, plugin.identifier, changed)
        if changed:
            log_setting_changes(actor, plugin.identifier, changed)
        return self.settings_of(plugin, manifest)


def _apply(
    plugin: Plugin, setting: Setting, row: PluginSettingValue | None, value: Any, actor
) -> bool:
    """Store one validated value; return whether anything changed."""
    if value is None:
        if row is None:
            return False
        row.delete()
        return True
    if setting.type == SECRET_TYPE:
        # Never decrypted to compare: a stored secret leaves its row only for the runtime
        # file, so writing one always counts as a change (and restarts the process).
        sealed = secret_encryption.encrypt(text=value)
        fields = {
            "value": None,
            "encrypted_value": sealed.encryptedtext,
            "tail": sealed.tail or None,
        }
    else:
        if row is not None and type(row.value) is type(value) and row.value == value:
            return False
        fields = {"value": value, "encrypted_value": None, "tail": None}
    PluginSettingValue.objects.update_or_create(
        plugin=plugin, key=setting.key, defaults={**fields, "updated_by": actor}
    )
    return True


def _value_problem(setting: Setting | None, value: Any) -> str | None:
    if setting is None:
        return "is not a setting of this plugin"
    if value is None:
        if setting.required and setting.default is None:
            return "is required and has no default, so it cannot be cleared"
        return None
    checker = _TYPE_CHECKS[setting.type]
    return checker(setting, value)


def _text_problem(value: Any, max_length: int) -> str | None:
    if not isinstance(value, str):
        return "must be a string"
    if len(value) > max_length:
        return f"must be at most {max_length} characters"
    return None


def _check_string(setting: Setting, value: Any) -> str | None:
    return _text_problem(value, MAX_STRING_LENGTH)


def _check_text(setting: Setting, value: Any) -> str | None:
    return _text_problem(value, MAX_TEXT_LENGTH)


def _check_integer(setting: Setting, value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return "must be an integer"
    if abs(value) > MAX_INTEGER_MAGNITUDE:
        return f"must be between -{MAX_INTEGER_MAGNITUDE} and {MAX_INTEGER_MAGNITUDE}"
    return None


def _check_boolean(setting: Setting, value: Any) -> str | None:
    return None if isinstance(value, bool) else "must be true or false"


def _check_url(setting: Setting, value: Any) -> str | None:
    if problem := _text_problem(value, MAX_URL_LENGTH):
        return problem
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
    except ValueError:
        hostname = None
        parts = None
    if (
        parts is None
        or parts.scheme not in ("http", "https")
        or not hostname
        or any(
            character.isspace() or unicodedata.category(character) == "Cc" for character in value
        )
    ):
        return "must be an http:// or https:// URL"
    return None


def _check_enum(setting: Setting, value: Any) -> str | None:
    if not isinstance(value, str) or value not in (setting.values or []):
        return f"must be one of {', '.join(setting.values or [])}"
    return None


def _check_secret(setting: Setting, value: Any) -> str | None:
    if not isinstance(value, str):
        return "must be a string"
    if not 1 <= len(value) <= MAX_SECRET_LENGTH:
        return f"must be 1 to {MAX_SECRET_LENGTH} characters"
    # secret_encryption caps the encoded size; many multi-byte characters can pass it.
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        return f"must be at most {MAX_TEXT_BYTES} bytes in UTF-8"
    return None


_TYPE_CHECKS = {
    "string": _check_string,
    "text": _check_text,
    "integer": _check_integer,
    "boolean": _check_boolean,
    "url": _check_url,
    "enum": _check_enum,
    SECRET_TYPE: _check_secret,
}
