from tables.models.rbac_models import ApiKey


class SystemServicePrincipal:
    """Synthetic request.user for system API keys.

    Satisfies IsAuthenticated (is_authenticated) and every superadmin gate
    (is_superadmin) without a User row. Deliberately has NO `email`/`pk` —
    user-context endpoints (profile) reject it via their user-identity checks.
    """

    is_authenticated = True
    is_superadmin = True

    def __str__(self) -> str:
        return "system-service"


class PrincipalResolver:
    """Maps an authenticated ApiKey to the principal it acts as."""

    def resolve(self, key: ApiKey):
        if key.key_type == ApiKey.KeyType.SYSTEM:
            return SystemServicePrincipal()
        # USER keys always have an owner (DB CheckConstraint).
        return key.created_by
