from dataclasses import dataclass, field

from django.db import transaction
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
    """Owns all organization-level persistent-variables behavior."""

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

    def build_run_variables(self, graph, user, payload) -> RunVariablesResult:
        payload = payload or {}
        graph_user = self._resolve_graph_user(graph, user)
        if not graph.enable_persistent_variables:
            return RunVariablesResult(variables=payload, graph_user=graph_user)
        graph_org, _ = GraphOrganization.objects.get_or_create(graph=graph)
        merged = self.deep_merge(graph_org.persistent_variables or {}, payload)
        return RunVariablesResult(variables=merged, graph_user=graph_user)

    def persist_session_results(self, session, final_variables) -> None:
        """Write tracked org values back at session END. Log-and-continue on error."""
        graph = session.graph
        if not graph.enable_persistent_variables:
            return
        if not final_variables:
            return
        try:
            start_node = StartNode.objects.filter(graph=graph).first()
            org_paths = self._org_paths(start_node.variables if start_node else {})
            if not org_paths:
                return
            with transaction.atomic():
                GraphOrganization.objects.get_or_create(graph=graph)
                graph_org = GraphOrganization.objects.select_for_update().get(
                    graph=graph
                )
                stored = graph_org.persistent_variables or {}
                changed = False
                for path in org_paths:
                    value = self.get_by_path(final_variables, path)
                    if value is _MISSING:
                        continue
                    existing = self.get_by_path(stored, path)
                    if existing is _MISSING or existing != value:
                        self._set_by_path(stored, path, value)
                        changed = True
                if changed:
                    graph_org.persistent_variables = stored
                    graph_org.save(update_fields=["persistent_variables"])
        except Exception as e:
            logger.error(f"Error persisting session results for graph {graph.id}: {e}")

    def sync_from_start_node(self, graph, old_variables, new_variables) -> None:
        """Mirror the declared org paths into storage; derive the flag (not gated)."""
        graph_org, _ = GraphOrganization.objects.get_or_create(graph=graph)
        old_paths = set(self._org_paths(old_variables))
        new_paths = set(self._org_paths(new_variables))
        defaults = self._actual(new_variables)
        stored = graph_org.persistent_variables or {}

        # Seed a path when it is newly declared, or declared-but-unstored.
        # Preserve the remembered value of a path that stays declared.
        for path in new_paths:
            if path in old_paths and self.get_by_path(stored, path) is not _MISSING:
                continue
            value = self.get_by_path(defaults, path)
            if value is not _MISSING:
                self._set_by_path(stored, path, value)
        for path in old_paths - new_paths:
            self._drop_path(stored, path)

        graph_org.persistent_variables = stored
        graph_org.save(update_fields=["persistent_variables"])

        enabled = bool(new_paths)
        if graph.enable_persistent_variables != enabled:
            graph.enable_persistent_variables = enabled
            graph.save(update_fields=["enable_persistent_variables"])

    def validate_start_node_variables(self, variables) -> None:
        """Every declared persistent path must exist under the Domain variables."""
        if not variables:
            return
        actual = self._actual(variables)
        persistent = variables.get(DOMAIN_PERSISTENT_KEY, {}) or {}
        # TODO refactor to use user_variable for persistent variables
        paths = (persistent.get(DOMAIN_ORGANIZATION_KEY) or []) + (
            persistent.get(DOMAIN_USER_KEY) or []
        )
        for path in paths:
            if self.get_by_path(actual, path) is _MISSING:
                raise serializers.ValidationError(
                    f"Path {path} in {DOMAIN_PERSISTENT_KEY} does not exist "
                    f"in {DOMAIN_VARIABLES_KEY}."
                )

    def _resolve_graph_user(self, graph, user):
        """The runner's per-flow row, get_or_create'd from their membership.

        None for anonymous/trigger runs and for superadmin (no membership row).
        No user-level variables flow through it in org-only scope; the row
        exists so `Session.graph_user` is a correct FK.
        """
        # TODO refactor to use user_variable for persistent variables
        if user is None or getattr(user, "is_superadmin", False):
            return None
        membership = OrganizationUser.objects.filter(
            user=user, org_id=graph.org_id, org__is_active=True
        ).first()
        if membership is None:
            return None
        graph_user, _ = GraphOrganizationUser.objects.get_or_create(
            graph=graph, organization_user=membership
        )
        return graph_user

    def seed_for_copy(self, new_graph, start_node_variables) -> GraphOrganization:
        """Create/seed a GraphOrganization for a copied or versioned graph (D4)."""
        start_node_variables = start_node_variables or {}
        persistent = self.extract(start_node_variables, DOMAIN_ORGANIZATION_KEY)
        graph_org, created = GraphOrganization.objects.get_or_create(
            graph=new_graph, defaults={"persistent_variables": persistent}
        )
        if not created:
            graph_org.persistent_variables = persistent
            graph_org.save(update_fields=["persistent_variables"])
        enabled = bool(self._org_paths(start_node_variables))
        if new_graph.enable_persistent_variables != enabled:
            new_graph.enable_persistent_variables = enabled
            new_graph.save(update_fields=["enable_persistent_variables"])
        return graph_org
