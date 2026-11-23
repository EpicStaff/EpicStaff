from rbac.validation.base import BaseRBACValidator, FieldError

ALLOWED_STATUS_FILTERS: tuple[str, ...] = ("active", "expired", "revoked")


class ApiKeyValidationService(BaseRBACValidator):
    """Validates POST /api/profile/api-keys/ input.

    `expires_in_days` semantics: absent → DEFAULT_TTL_DAYS; explicit null →
    no expiry; otherwise an int in [1, MAX_TTL_DAYS].
    """

    MAX_NAME_LENGTH = 255
    DEFAULT_TTL_DAYS = 90
    MAX_TTL_DAYS = 3650

    def validate_create(self, data):
        errors: list[FieldError] = []

        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(FieldError("name", "Name is required."))
        elif len(name.strip()) > self.MAX_NAME_LENGTH:
            errors.append(
                FieldError("name", f"Name must be at most {self.MAX_NAME_LENGTH} characters.")
            )

        if "expires_in_days" in data:
            expires_in_days = data["expires_in_days"]
            if expires_in_days is not None and (
                isinstance(expires_in_days, bool)
                or not isinstance(expires_in_days, int)
                or not 1 <= expires_in_days <= self.MAX_TTL_DAYS
            ):
                errors.append(
                    FieldError(
                        "expires_in_days",
                        f"Must be null (no expiry) or an integer between 1 and {self.MAX_TTL_DAYS}.",
                    )
                )
        else:
            expires_in_days = self.DEFAULT_TTL_DAYS

        org_id = data.get("org_id")
        if org_id is None:
            errors.append(FieldError("org_id", "Organization is required."))
        elif isinstance(org_id, bool) or not isinstance(org_id, int) or org_id < 1:
            errors.append(FieldError("org_id", "Must be a positive integer."))

        self._raise_if_any(errors)
        return {"name": name.strip(), "expires_in_days": expires_in_days, "org_id": org_id}

    def validate_list_keys_query(self, params) -> dict:
        """`GET /api/admin/api-keys/` filters: ?user=&status=&search=."""
        errors: list[FieldError] = []

        raw_status: str | None = params.get("status")
        status_value: str | None = raw_status or None
        if status_value is not None and status_value not in ALLOWED_STATUS_FILTERS:
            errors.append(
                FieldError("status", f"Must be one of {', '.join(ALLOWED_STATUS_FILTERS)}.")
            )

        raw_owner: str | None = params.get("user")
        owner_id: int | None = None
        if raw_owner not in (None, ""):
            try:
                owner_id = int(raw_owner)
            except (TypeError, ValueError):
                errors.append(FieldError("user", "Must be an integer user id."))

        self._raise_if_any(errors)

        search: str | None = params.get("search")
        return {
            "owner_id": owner_id,
            "status_value": status_value,
            "search": search or None,
        }
