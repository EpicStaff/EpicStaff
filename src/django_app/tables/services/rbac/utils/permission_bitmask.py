"""Conversion between action-code lists (wire format) and the
`Permission` IntFlag bitmask (storage format).

The API never exposes raw bitmask integers — they're storage. The FE
sends action codes (e.g. ["create", "read"]) and the API converts to/from
bitmask at the boundary.
"""

from tables.models.rbac_models.rbac_enums import Permission


_ACTION_CODE_TO_BIT = {
    "create": Permission.CREATE,
    "read": Permission.READ,
    "update": Permission.UPDATE,
    "delete": Permission.DELETE,
    "export": Permission.EXPORT,
    "use": Permission.USE,
    "list": Permission.LIST,
}


def actions_to_bitmask(action_codes: list[str]) -> int:
    """Combine a list of action codes into a bitmask integer.
    Raises ValueError for unknown codes."""
    mask = 0
    for code in action_codes:
        bit = _ACTION_CODE_TO_BIT.get(code)
        if bit is None:
            raise ValueError(f"Unknown action code: {code!r}")
        mask |= int(bit)
    return mask


def bitmask_to_actions(bitmask: int, applicable: list[str]) -> list[str]:
    """Expand a bitmask into the subset of `applicable` action codes
    that are set in the bitmask. Order is preserved from `applicable`
    (which itself follows catalog order)."""
    return [code for code in applicable if bitmask & int(_ACTION_CODE_TO_BIT[code])]
