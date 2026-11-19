"""Mappings from DRF action names to required `Permission` bits.

`HasOrgPermission` reads a view's `rbac_action_map` and falls back to
`DEFAULT_ACTION_MAP` when the view declares none. `FLOW_CONTENT_ACTION_MAP`
is for the viewsets over a flow's nodes, edges and notes.
"""

from rbac.models.enums import Permission

DEFAULT_ACTION_MAP = {
    "list": Permission.READ,  # TODO: refactor for list permissions
    "retrieve": Permission.READ,
    "create": Permission.CREATE,
    "update": Permission.UPDATE,
    "partial_update": Permission.UPDATE,
    "destroy": Permission.DELETE,
}

# For viewsets whose rows are a flow's content (nodes, edges, notes). Adding,
# changing or removing one edits the flow, so every write needs UPDATE, the same
# bit the bulk flow save needs. Creating or deleting the flow itself stays on
# DEFAULT_ACTION_MAP.
FLOW_CONTENT_ACTION_MAP = {
    "list": Permission.READ,
    "retrieve": Permission.READ,
    "create": Permission.UPDATE,
    "update": Permission.UPDATE,
    "partial_update": Permission.UPDATE,
    "destroy": Permission.UPDATE,
}
