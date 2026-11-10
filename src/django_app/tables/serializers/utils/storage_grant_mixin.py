from rest_framework import serializers

_ACTIONS = ("read", "write", "delete")


class StorageGrantFlagsMixin:
    """Keeps the storage grant flags of a node serializer consistent, and defaults new nodes to all off.

    Put it first in the bases: it wraps `run_validation`, which runs after the class's own
    `validate`. Set `storage_grant_prefixes` to the column prefixes of the node's slots
    ("" for a node with one grant; "pre_" and "post_" for a classification decision table).

    - A new node sent without the flags gets all of them False: it runs with no access to
      the flow's files until someone grants it.
    - A slot is always saved whole: sending some of the three fills the rest from the
      stored value, or False when the slot is not configured; all three null clear it.
      Mixing null with true or false is a validation error.
    """

    storage_grant_prefixes: tuple[str, ...] = ("",)

    def run_validation(self, data=serializers.empty):
        validated = super().run_validation(data)
        for prefix in self.storage_grant_prefixes:
            self._normalize_slot(validated, prefix)
        return validated

    def _normalize_slot(self, validated: dict, prefix: str) -> None:
        names = [f"{prefix}storage_grant_{action}" for action in _ACTIONS]
        sent = [name for name in names if name in validated]
        instance = self.instance
        if not sent:
            if instance is None:
                validated.update(dict.fromkeys(names, False))
            return
        stored = [getattr(instance, name) if instance is not None else None for name in names]
        merged = [
            validated.get(name, stored_value)
            for name, stored_value in zip(names, stored, strict=True)
        ]
        explicit_null = any(name in validated and validated[name] is None for name in names)
        if explicit_null and any(value is not None for value in merged):
            raise serializers.ValidationError(
                {names[0]: "Send all three storage grant flags together, or all null."}
            )
        for name, value in zip(names, merged, strict=True):
            validated[name] = value if value is not None or explicit_null else False
