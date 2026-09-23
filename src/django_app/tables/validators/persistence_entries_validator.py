from typing import Any

from rest_framework import serializers

from tables.constants.persistence_constants import MAX_KEY_LENGTH

_REQUIRED_FIELDS = {
    "read": ("alias", "key"),
    "write": ("key", "value"),
    "delete": ("key",),
}
_ALLOWED_FIELDS = {
    "read": {"alias", "key", "default"},
    "write": {"key", "value"},
    "delete": {"key"},
}


class PersistenceEntriesValidator:
    """Structural rules for PersistenceNode.entries. Key templates are rendered by crew."""

    def validate(self, mode: str, entries: Any) -> list[dict]:
        if not isinstance(entries, list):
            raise serializers.ValidationError({"entries": "Must be a list."})
        errors: list[str] = []
        aliases: set[str] = set()
        for index, entry in enumerate(entries):
            error = self._entry_error(mode, entry, aliases)
            if error:
                errors.append(f"Entry {index}: {error}")
        if errors:
            raise serializers.ValidationError({"entries": errors})
        return entries

    def _entry_error(self, mode: str, entry: Any, aliases: set[str]) -> str | None:
        if not isinstance(entry, dict):
            return "must be an object."
        unknown = set(entry) - _ALLOWED_FIELDS[mode]
        if unknown:
            return f"unknown fields {sorted(unknown)} for mode '{mode}'."
        for field in _REQUIRED_FIELDS[mode]:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                return f"'{field}' must be a non-empty string."
        if len(entry["key"]) > MAX_KEY_LENGTH:
            return f"'key' must be at most {MAX_KEY_LENGTH} characters."
        if mode == "read":
            if entry["alias"] in aliases:
                return f"duplicate alias '{entry['alias']}'."
            aliases.add(entry["alias"])
        return None
