import re
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
# Crew's `variables` is a DotDict, so a path must start with a key (`variables[0]` never
# resolves). A prefix match leaves room for the `|default` suffix; ASCII matches the frontend.
_STATE_PATH = re.compile(r"^variables\.\w", re.ASCII)


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
        if mode == "write":
            # Crew keeps the `|default` text verbatim, so `variables.x|0 ` would default to "0 ".
            return [{**entry, "value": entry["value"].strip()} for entry in entries]
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
        if mode == "write" and not _STATE_PATH.match(entry["value"].strip()):
            return "'value' must be a state path like 'variables.user.name'."
        if mode == "read":
            if entry["alias"] in aliases:
                return f"duplicate alias '{entry['alias']}'."
            aliases.add(entry["alias"])
        return None
