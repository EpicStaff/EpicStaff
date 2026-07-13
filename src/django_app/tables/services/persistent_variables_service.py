from dataclasses import dataclass, field

from loguru import logger
from rest_framework import serializers

from tables.constants.variables_constants import (
    DOMAIN_ORGANIZATION_KEY,
    DOMAIN_PERSISTENT_KEY,
    DOMAIN_USER_KEY,
    DOMAIN_VARIABLES_KEY,
)
from tables.models.graph_models import (
    GraphOrganization,
    GraphOrganizationUser,
    StartNode,
)
from tables.models.rbac_models import OrganizationUser

# Sentinel distinguishing "key absent" from "value is explicitly None".
_MISSING = object()


@dataclass
class RunVariablesResult:
    variables: dict
    graph_user: GraphOrganizationUser | None = None
    warnings: list = field(default_factory=list)


class PersistentVariablesService:
    """Owns all organization-level persistent-variables behavior (EST-3056)."""

    # ---------------- path utils ----------------
    def get_by_path(self, source: dict, path: str):
        """Return the value at a dot-path, or `_MISSING` if any key is absent."""
        current = source
        for key in path.split("."):
            if not isinstance(current, dict) or key not in current:
                return _MISSING
            current = current[key]
        return current

    def _set_by_path(self, target: dict, path: str, value) -> None:
        current = target
        keys = path.split(".")
        for key in keys[:-1]:
            current = current.setdefault(key, {})
        current[keys[-1]] = value

    def _drop_path(self, target: dict, path: str) -> None:
        keys = path.split(".")
        stack = []
        current = target
        for key in keys[:-1]:
            if not isinstance(current, dict) or key not in current:
                return
            stack.append((current, key))
            current = current[key]
        if isinstance(current, dict):
            current.pop(keys[-1], None)
        # prune now-empty parent dicts
        for parent, key in reversed(stack):
            if isinstance(parent.get(key), dict) and not parent[key]:
                parent.pop(key, None)

    def deep_merge(self, base: dict, updates: dict) -> dict:
        """Merge `updates` over `base`, recursing into nested dicts. Pure."""
        result = dict(base or {})
        for key, value in (updates or {}).items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self.deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    # ---------------- config helpers ----------------
    def _org_paths(self, variables: dict) -> list:
        return (
            (variables or {})
            .get(DOMAIN_PERSISTENT_KEY, {})
            .get(DOMAIN_ORGANIZATION_KEY, [])
        ) or []

    def _actual(self, variables: dict) -> dict:
        return (variables or {}).get(DOMAIN_VARIABLES_KEY, {}) or {}

    def extract(self, variables: dict, domain_key: str) -> dict:
        """Extract the values for a domain's declared paths from the Domain defaults."""
        paths = (
            (variables or {}).get(DOMAIN_PERSISTENT_KEY, {}).get(domain_key, [])
        ) or []
        actual = self._actual(variables)
        result: dict = {}
        for path in paths:
            value = self.get_by_path(actual, path)
            if value is _MISSING:
                continue
            self._set_by_path(result, path, value)
        return result
