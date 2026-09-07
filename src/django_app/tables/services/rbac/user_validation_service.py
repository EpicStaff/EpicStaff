from typing import Any

from django.core.files.uploadedfile import UploadedFile

from tables.services.rbac.base_rbac_validator import BaseRBACValidator, FieldError


class UserValidationService(BaseRBACValidator):
    """Validates request payloads for Story 5 user-management endpoints.

    Each public method runs every applicable check, accumulates failures as
    `FieldError`, and raises a single `FormValidationError` carrying the
    structured `errors[]` list. Returns the cleaned payload on success.

    Sensitive submitted values (password) are redacted from the echoed
    error responses; non-sensitive values (email, role_id, user_id) are
    echoed as-is so the FE can highlight the offending input.
    """

    _redacted_fields = frozenset(
        {"password", "new_password", "current_password", "ticket"}
    )

    # ---- create_user ----

    def validate_create_user(self, data: dict) -> dict:
        """`POST /api/admin/users/`. Body: email, password, optional
        organization_id, optional role_id (only meaningful when
        organization_id is given)."""
        email = data.get("email")
        password = data.get("password")
        organization_id = data.get("organization_id")
        role_id = data.get("role_id")

        errors: list[FieldError] = []
        errors.extend(self._validate_email_field(email))
        errors.extend(
            self._validate_password_field(password, user_hints={"email": email})
        )
        if organization_id is not None:
            errors.extend(
                self._validate_positive_int_field("organization_id", organization_id)
            )
            if role_id is not None:
                errors.extend(self._validate_positive_int_field("role_id", role_id))

        self._raise_if_any(errors)
        return {
            "email": email,
            "password": password,
            "organization_id": int(organization_id)
            if organization_id is not None
            else None,
            "role_id": int(role_id) if role_id is not None else None,
        }

    # ---- change_role ----

    def validate_change_role(self, data: dict) -> dict:
        """Body: {role_id}. role_id is required. Shared by the flat
        `PATCH /api/admin/memberships/{id}/` surface."""
        role_id = data.get("role_id")
        errors: list[FieldError] = []
        errors.extend(self._validate_positive_int_field("role_id", role_id))
        self._raise_if_any(errors)
        return {"role_id": int(role_id)}

    # ---- add_member (POST /api/admin/memberships/) ----

    def validate_add_member(self, data: dict) -> dict:
        """`POST /api/admin/memberships/` — link an existing account to an
        org. Requires org_id + role_id and EXACTLY ONE of email | user_id
        (account creation stays a superadmin-only op)."""
        org_id = data.get("org_id")
        role_id = data.get("role_id")
        email = data.get("email")
        user_id = data.get("user_id")

        errors: list[FieldError] = []
        errors.extend(self._validate_positive_int_field("org_id", org_id))
        errors.extend(self._validate_positive_int_field("role_id", role_id))

        has_email = email is not None and email != ""
        has_user_id = user_id is not None and user_id != ""
        if has_email and has_user_id:
            errors.append(
                FieldError(
                    "email",
                    email,
                    "Provide exactly one of email or user_id, not both.",
                )
            )
        elif not has_email and not has_user_id:
            errors.append(
                FieldError("email", None, "Provide exactly one of email or user_id.")
            )
        elif has_email:
            errors.extend(self._validate_email_field(email))
        else:
            errors.extend(self._validate_positive_int_field("user_id", user_id))

        self._raise_if_any(errors)
        return {
            "org_id": int(org_id),
            "role_id": int(role_id),
            "email": email if has_email else None,
            "user_id": int(user_id) if has_user_id else None,
        }

    def validate_list_memberships_query(self, params) -> dict:
        """`GET /api/admin/memberships/` filters: ?search=&role_id=&status=.
        role_id must be a positive int; status must be active|inactive."""
        search = params.get("search")
        role_id_raw = params.get("role_id")
        status_raw = params.get("status")

        errors: list[FieldError] = []
        role_id = None
        if role_id_raw not in (None, ""):
            role_id_errors = self._validate_positive_int_field("role_id", role_id_raw)
            errors.extend(role_id_errors)
            if not role_id_errors:
                role_id = int(role_id_raw)

        status_value = None
        if status_raw not in (None, ""):
            if status_raw in ("active", "inactive"):
                status_value = status_raw
            else:
                errors.append(
                    FieldError(
                        "status", status_raw, "Must be one of: active, inactive."
                    )
                )

        self._raise_if_any(errors)
        return {
            "search": search if search else None,
            "role_id": role_id,
            "status_value": status_value,
        }

    # ---- list-users query params ----

    def validate_list_users_query(self, params: dict) -> dict:
        """Optional filters: ?email=substr&is_superadmin=bool&organization_id=N."""
        email = params.get("email")
        is_superadmin_raw = params.get("is_superadmin")
        organization_id_raw = params.get("organization_id")

        errors: list[FieldError] = []

        is_superadmin: Any = None
        if is_superadmin_raw is not None and is_superadmin_raw != "":
            normalized = str(is_superadmin_raw).strip().lower()
            if normalized in ("true", "1"):
                is_superadmin = True
            elif normalized in ("false", "0"):
                is_superadmin = False
            else:
                errors.append(
                    FieldError(
                        "is_superadmin",
                        is_superadmin_raw,
                        "Must be one of: true, false, 1, 0.",
                    )
                )

        organization_id: Any = None
        if organization_id_raw is not None and organization_id_raw != "":
            errors.extend(
                self._validate_positive_int_field(
                    "organization_id", organization_id_raw
                )
            )
            if not errors or errors[-1].field != "organization_id":
                organization_id = int(organization_id_raw)

        self._raise_if_any(errors)
        return {
            "email": email if email else None,
            "is_superadmin": is_superadmin,
            "organization_id": organization_id,
        }

    # ---- Story 6: profile ----

    def validate_profile_patch(self, data: dict) -> dict:
        """`PATCH /api/profile/`.

        Returns a cleaned dict containing only the keys that were in
        `data` and that passed validation. Unknown keys are silently
        ignored — they cannot reach the service.

        Now: display_name is the only mutable field. Future fields
        land here as additional branches.
        """
        cleaned: dict = {}
        errors: list[FieldError] = []

        if "display_name" in data:
            value = data["display_name"]
            if value is None:
                cleaned["display_name"] = None
            elif not isinstance(value, str):
                errors.append(
                    FieldError(
                        "display_name",
                        self._echo("display_name", value),
                        "Must be a string or null.",
                    )
                )
            else:
                trimmed = value.strip()
                if len(trimmed) == 0:
                    errors.append(
                        FieldError(
                            "display_name",
                            self._echo("display_name", value),
                            "Must not be blank. Use null to clear.",
                        )
                    )
                elif len(trimmed) > 255:
                    errors.append(
                        FieldError(
                            "display_name",
                            self._echo("display_name", value),
                            "Must be 255 characters or fewer.",
                        )
                    )
                else:
                    cleaned["display_name"] = trimmed

        self._raise_if_any(errors)
        return cleaned

    def validate_avatar_upload(self, data) -> UploadedFile:
        """`POST /api/profile/avatar/`.

        Shape only: `avatar` key present and is an UploadedFile. Size and
        content validation live in UserAvatarStorageService and raise
        their own typed exceptions.
        """
        file = data.get("avatar") if hasattr(data, "get") else None
        errors: list[FieldError] = []
        if file is None:
            errors.append(FieldError("avatar", None, "This field is required."))
        elif not isinstance(file, UploadedFile):
            errors.append(FieldError("avatar", "<non-file>", "Must be a file upload."))
        self._raise_if_any(errors)
        return file

    def validate_password_change_request(self, data: dict) -> dict:
        """`POST /api/profile/password-change/request/`. Body: current_password."""
        current_password = data.get("current_password")
        errors: list[FieldError] = []
        errors.extend(
            self._require_nonblank_string("current_password", current_password)
        )
        self._raise_if_any(errors)
        return {"current_password": current_password}

    def validate_password_change_confirm(self, data: dict) -> dict:
        """`POST /api/profile/password-change/confirm/`. Body: ticket, new_password."""
        ticket = data.get("ticket")
        new_password = data.get("new_password")
        errors: list[FieldError] = []
        errors.extend(self._require_nonblank_string("ticket", ticket))
        errors.extend(
            self._validate_password_field(new_password, field_name="new_password")
        )
        self._raise_if_any(errors)
        return {"ticket": ticket, "new_password": new_password}
