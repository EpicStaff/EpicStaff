from tables.services.rbac.rbac_exceptions import FormValidationError


class ApiKeyValidationService:
    """Validates POST /api/profile/api-keys/ input.

    `expires_in_days` semantics: absent → DEFAULT_TTL_DAYS; explicit null →
    no expiry; otherwise an int in [1, MAX_TTL_DAYS].
    """

    MAX_NAME_LENGTH = 255
    DEFAULT_TTL_DAYS = 90
    MAX_TTL_DAYS = 3650

    def validate_create(self, data):
        errors = []

        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(
                {"field": "name", "value": name, "reason": "Name is required."}
            )
        elif len(name.strip()) > self.MAX_NAME_LENGTH:
            errors.append(
                {
                    "field": "name",
                    "value": name[:32],
                    "reason": f"Name must be at most {self.MAX_NAME_LENGTH} characters.",
                }
            )

        if "expires_in_days" in data:
            expires_in_days = data["expires_in_days"]
            if expires_in_days is not None and (
                isinstance(expires_in_days, bool)
                or not isinstance(expires_in_days, int)
                or not 1 <= expires_in_days <= self.MAX_TTL_DAYS
            ):
                errors.append(
                    {
                        "field": "expires_in_days",
                        "value": expires_in_days,
                        "reason": (
                            "Must be null (no expiry) or an integer between "
                            f"1 and {self.MAX_TTL_DAYS}."
                        ),
                    }
                )
        else:
            expires_in_days = self.DEFAULT_TTL_DAYS

        if errors:
            raise FormValidationError(errors)

        return {"name": name.strip(), "expires_in_days": expires_in_days}
