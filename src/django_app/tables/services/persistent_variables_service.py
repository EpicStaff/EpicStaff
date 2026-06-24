from tables.constants.variables_constants import (
    DOMAIN_ORGANIZATION_KEY,
    DOMAIN_PERSISTENT_KEY,
    DOMAIN_USER_KEY,
    DOMAIN_VARIABLES_KEY,
)
from tables.models.graph_models import GraphOrganization


# TODO: refactor, persistant variables story
class PersistentVariablesService:
    def extract(self, variables: dict, domain_key: str) -> dict:
        """Extract persistent variable values from StartNode variables for a given domain."""
        paths = variables.get(DOMAIN_PERSISTENT_KEY, {}).get(domain_key, [])
        if not paths:
            return {}
        result = {}
        actual = variables.get(DOMAIN_VARIABLES_KEY, {})
        for path in paths:
            value = self.get_by_path(actual, path)
            if value is None:
                continue
            self._set_by_path(result, path, value)
        return result

    def sync_graph_organization(
        self,
        graph_organization: GraphOrganization,
        old_variables: dict,
        new_variables: dict,
    ) -> None:
        """Update GraphOrganization's persistent values if tracked paths have changed."""
        if self._should_update(
            old_variables,
            new_variables,
            graph_organization.persistent_variables or {},
            DOMAIN_ORGANIZATION_KEY,
        ):
            graph_organization.persistent_variables = self.extract(
                new_variables, DOMAIN_ORGANIZATION_KEY
            )

        if self._should_update(
            old_variables,
            new_variables,
            graph_organization.user_variables or {},
            DOMAIN_USER_KEY,
        ):
            graph_organization.user_variables = self.extract(
                new_variables, DOMAIN_USER_KEY
            )

        graph_organization.save()

    def _should_update(
        self, old_vars: dict, new_vars: dict, existing_persistent: dict, domain_key: str
    ) -> bool:
        """
        Check if we should update persistent storage:
        1. If tracked paths changed
        2. If persistent storage is empty but we have paths to track
        """
        old_paths = set(old_vars.get(DOMAIN_PERSISTENT_KEY, {}).get(domain_key, []))
        new_paths = set(new_vars.get(DOMAIN_PERSISTENT_KEY, {}).get(domain_key, []))

        if old_paths != new_paths:
            return True
        if new_paths and not existing_persistent:
            return True

        return False

    def get_by_path(self, source: dict, path: str):
        """Get value from nested dict by dot-path. Returns None if path not found."""
        current = source
        try:
            for key in path.split("."):
                current = current[key]
            return current
        except (KeyError, TypeError):
            return None

    def _set_by_path(self, target: dict, path: str, value) -> None:
        current = target
        keys = path.split(".")
        for key in keys[:-1]:
            current = current.setdefault(key, {})
        current[keys[-1]] = value
