from tables.services.rbac.rbac_exceptions import FormValidationError

_DRY_RUN_TRUE = {"true", "1"}
_DRY_RUN_FALSE = {"false", "0", ""}


def parse_dry_run(raw: str | None) -> bool:
    """Parse the `dry_run` query parameter, defaulting to a real delete."""
    if raw is None:
        return False
    normalized = raw.strip().lower()
    if normalized in _DRY_RUN_TRUE:
        return True
    if normalized in _DRY_RUN_FALSE:
        return False
    raise FormValidationError(
        errors=[
            {
                "field": "dry_run",
                "value": raw,
                "reason": "Must be one of: true, false, 1, 0.",
            }
        ]
    )
