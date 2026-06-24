"""Default mapping from DRF action names to required `Permission` bits.

Used by `HasOrgPermission` when a view does not declare its own
`rbac_action_map`. Views can override per-action; this map is
the fallback only.
"""

from tables.models.rbac_models.rbac_enums import Permission


DEFAULT_ACTION_MAP = {
    "list": Permission.READ,  # TODO: refactor for list permissions
    "retrieve": Permission.READ,
    "create": Permission.CREATE,
    "update": Permission.UPDATE,
    "partial_update": Permission.UPDATE,
    "destroy": Permission.DELETE,
}
