from collections.abc import Mapping
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from tables.models.user import (
    SHORTCUTS_MAX_CUSTOM_ENTRIES,
    SHORTCUTS_MAX_OVERRIDE_ENTRIES,
    SHORTCUTS_MAX_PARAM_INTEGER,
    SHORTCUTS_MAX_PARAMS,
    SHORTCUTS_MAX_TEXT_LENGTH,
)

from rbac.validation.base import BaseRBACValidator, FieldError

_CUSTOM_ENTRY_SHAPE_REASON = (
    '"custom" must be a list of objects with exactly the keys "action" and "keys", '
    'plus an optional "params".'
)


class UserValidationService(BaseRBACValidator):
    """Validates request payloads for Story 5 user-management endpoints.

    Each public method runs every applicable check, accumulates failures as
    `FieldError`, and raises a single `FormValidationError` carrying the
    structured `errors[]` list. Returns the cleaned payload on success.

    Sensitive submitted values (password) are redacted from the echoed
    error responses; non-sensitive values (email, role_id, user_id) are
    echoed as-is so the FE can highlight the offending input.
    """

    _redacted_fields = frozenset({"password", "new_password", "current_password", "ticket"})

    # ---- create_user ----

    def validate_create_user(self, data: dict) -> dict:
        """`POST /api/admin/users/`. Body: email, password, optional
        display_name, optional organization_id, optional role_id (only
        meaningful when organization_id is given)."""
        email = data.get("email")
        password = data.get("password")
        organization_id = data.get("organization_id")
        role_id = data.get("role_id")

        errors: list[FieldError] = []
        errors.extend(self._validate_new_account_email(email))
        errors.extend(self._validate_password_field(password, user=self._prospective_user(email)))
        display_name, display_name_errors = self._clean_display_name(data.get("display_name"))
        errors.extend(display_name_errors)
        if organization_id is not None:
            errors.extend(self._validate_positive_int_field("organization_id", organization_id))
            if role_id is not None:
                errors.extend(self._validate_positive_int_field("role_id", role_id))

        self._raise_if_any(errors)
        return {
            "email": email,
            "password": password,
            "display_name": display_name,
            "organization_id": int(organization_id) if organization_id is not None else None,
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
            errors.append(FieldError("email", None, "Provide exactly one of email or user_id."))
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
        errors: list[FieldError] = []
        role_id, role_errors = self._parse_role_id(params.get("role_id"))
        errors.extend(role_errors)
        status_value, status_errors = self._parse_status(params.get("status"))
        errors.extend(status_errors)

        search = params.get("search")
        self._raise_if_any(errors)
        return {
            "search": search if search else None,
            "role_id": role_id,
            "status_value": status_value,
        }

    def _parse_role_id(self, raw) -> tuple[Any, list[FieldError]]:
        if raw in (None, ""):
            return None, []
        errors = self._validate_positive_int_field("role_id", raw)
        return (None if errors else int(raw)), errors

    def _parse_status(self, raw) -> tuple[Any, list[FieldError]]:
        if raw in (None, ""):
            return None, []
        if raw in ("active", "inactive"):
            return raw, []
        return None, [FieldError("status", raw, "Must be one of: active, inactive.")]

    # ---- list-users query params ----

    def validate_list_users_query(self, params) -> dict:
        """`GET /api/admin/users/` filters:
        ?search=&email=&is_superadmin=&status=&role_id=&organization_id=.

        `search` supersedes the narrower `email`; `?org_ids=` is parsed by the
        view (it carries its own error envelope) and supersedes
        `organization_id` there.
        """
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
            org_errors = self._validate_positive_int_field("organization_id", organization_id_raw)
            errors.extend(org_errors)
            if not org_errors:
                organization_id = int(organization_id_raw)

        role_id, role_errors = self._parse_role_id(params.get("role_id"))
        errors.extend(role_errors)
        status_value, status_errors = self._parse_status(params.get("status"))
        errors.extend(status_errors)

        search = params.get("search") or params.get("email")
        self._raise_if_any(errors)
        return {
            "search": search if search else None,
            "is_superadmin": is_superadmin,
            "organization_id": organization_id,
            "role_id": role_id,
            "status_value": status_value,
        }

    # ---- Story 6: profile ----

    def validate_profile_patch(self, data: Any) -> dict:
        """`PATCH /api/profile/`.

        Returns a cleaned dict containing only the keys that were in
        `data` and that passed validation. Unknown keys are silently
        ignored — they cannot reach the service.

        Mutable fields: display_name and custom_shortcuts. The view
        writes nothing until this returns, so one invalid field rejects
        the whole PATCH.
        """
        if not isinstance(data, Mapping):
            self._raise_if_any([FieldError("body", None, "Request body must be a JSON object.")])

        cleaned: dict = {}
        errors: list[FieldError] = []

        if "display_name" in data:
            display_name, display_name_errors = self._clean_display_name(
                data["display_name"], blank_reason="Must not be blank. Use null to clear."
            )
            errors.extend(display_name_errors)
            if not display_name_errors:
                cleaned["display_name"] = display_name

        if "custom_shortcuts" in data:
            custom_shortcuts_reason = self._custom_shortcuts_error(data["custom_shortcuts"])
            if custom_shortcuts_reason is None:
                cleaned["custom_shortcuts"] = data["custom_shortcuts"]
            else:
                errors.append(FieldError("custom_shortcuts", None, custom_shortcuts_reason))

        self._raise_if_any(errors)
        return cleaned

    @staticmethod
    def _custom_shortcuts_error(value: Any) -> str | None:
        if not isinstance(value, dict) or value.keys() != {"custom", "overrides"}:
            return 'Must be an object with exactly the keys "custom" and "overrides".'
        custom = value["custom"]
        overrides = value["overrides"]
        if not isinstance(custom, list):
            return _CUSTOM_ENTRY_SHAPE_REASON
        if not isinstance(overrides, dict):
            return '"overrides" must be an object mapping action ids to keys or null.'
        if len(custom) > SHORTCUTS_MAX_CUSTOM_ENTRIES:
            return f'"custom" must have {SHORTCUTS_MAX_CUSTOM_ENTRIES} entries or fewer.'
        if len(overrides) > SHORTCUTS_MAX_OVERRIDE_ENTRIES:
            return f'"overrides" must have {SHORTCUTS_MAX_OVERRIDE_ENTRIES} entries or fewer.'
        if not all(_has_shortcut_entry_shape(entry) for entry in custom):
            return _CUSTOM_ENTRY_SHAPE_REASON
        params_list = [entry["params"] for entry in custom if "params" in entry]
        if not all(
            isinstance(params, dict) and 0 < len(params) <= SHORTCUTS_MAX_PARAMS
            for params in params_list
        ):
            return f'"params" must be an object with 1 to {SHORTCUTS_MAX_PARAMS} entries.'
        action_ids = [entry["action"] for entry in custom] + list(overrides)
        if not all(_is_shortcut_text(action_id) for action_id in action_ids):
            return (
                "Action ids must be non-empty printable ASCII strings "
                f"of {SHORTCUTS_MAX_TEXT_LENGTH} characters or fewer."
            )
        assigned_keys = [entry["keys"] for entry in custom if entry["keys"] is not None] + [
            keys for keys in overrides.values() if keys is not None
        ]
        if not all(_is_shortcut_text(keys) for keys in assigned_keys):
            return (
                "Keys must be null or non-empty printable ASCII strings "
                f"of {SHORTCUTS_MAX_TEXT_LENGTH} characters or fewer."
            )
        if not all(
            _is_shortcut_text(name) and _is_shortcut_param_value(param_value)
            for params in params_list
            for name, param_value in params.items()
        ):
            return (
                "Param names must be non-empty printable ASCII strings "
                f"of {SHORTCUTS_MAX_TEXT_LENGTH} characters or fewer; each value must be "
                f"such a string or an integer from 0 to {SHORTCUTS_MAX_PARAM_INTEGER}."
            )
        if len(set(assigned_keys)) != len(assigned_keys):
            return 'Keys must not repeat across "custom" entries and "overrides".'
        return None

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
        errors.extend(self._require_nonblank_string("current_password", current_password))
        self._raise_if_any(errors)
        return {"current_password": current_password}

    def validate_password_change_confirm(self, data: dict) -> dict:
        """`POST /api/profile/password-change/confirm/`. Body: ticket, new_password."""
        ticket = data.get("ticket")
        new_password = data.get("new_password")
        errors: list[FieldError] = []
        errors.extend(self._require_nonblank_string("ticket", ticket))
        errors.extend(
            self._validate_password_field(new_password, user=None, field_name="new_password")
        )
        self._raise_if_any(errors)
        return {"ticket": ticket, "new_password": new_password}


def _has_shortcut_entry_shape(entry: Any) -> bool:
    return isinstance(entry, dict) and entry.keys() in (
        {"action", "keys"},
        {"action", "keys", "params"},
    )


def _is_shortcut_param_value(param_value: Any) -> bool:
    if type(param_value) is int:
        return 0 <= param_value <= SHORTCUTS_MAX_PARAM_INTEGER
    return _is_shortcut_text(param_value)


def _is_shortcut_text(text: Any) -> bool:
    return (
        isinstance(text, str)
        and 0 < len(text) <= SHORTCUTS_MAX_TEXT_LENGTH
        and text.isascii()
        and text.isprintable()
    )
