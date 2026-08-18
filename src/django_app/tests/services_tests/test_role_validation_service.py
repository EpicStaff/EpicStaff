import pytest

from tables.models.rbac_models.rbac_enums import Permission
from tables.services.rbac.rbac_exceptions import FormValidationError
from tables.services.rbac.role_validation_service import RoleValidationService


@pytest.fixture
def validator():
    return RoleValidationService()


def test_validate_create_happy_path(validator):
    cleaned = validator.validate_create(
        {
            "org_id": 10,
            "name": "  Billing Manager ",
            "description": "manage billing",
            "permissions": [
                {"resource_type": "secrets", "actions": ["read", "update"]}
            ],
        }
    )
    assert cleaned["org_id"] == 10
    assert cleaned["name"] == "Billing Manager"  # trimmed
    assert cleaned["permissions"] == [
        {
            "resource_type": "secrets",
            "bitmask": int(Permission.READ | Permission.UPDATE),
        }
    ]


def test_validate_create_empty_permissions_allowed(validator):
    cleaned = validator.validate_create({"org_id": 10, "name": "No Access"})
    assert cleaned["permissions"] == []


def test_validate_create_reserved_name_rejected(validator):
    with pytest.raises(FormValidationError) as exc:
        validator.validate_create({"org_id": 10, "name": "Org Admin"})
    assert any(e["field"] == "name" for e in exc.value.errors)


def test_validate_create_blank_name_rejected(validator):
    with pytest.raises(FormValidationError):
        validator.validate_create({"org_id": 10, "name": "   "})


def test_validate_create_missing_org_id_rejected(validator):
    with pytest.raises(FormValidationError):
        validator.validate_create({"name": "X"})


def test_validate_create_inapplicable_action_rejected(validator):
    # secrets does not have "export" in the catalog's applicable_actions.
    with pytest.raises(FormValidationError) as exc:
        validator.validate_create(
            {
                "org_id": 10,
                "name": "Bad",
                "permissions": [{"resource_type": "secrets", "actions": ["export"]}],
            }
        )
    assert any("secrets" in e["field"] for e in exc.value.errors)


def test_validate_create_unknown_resource_rejected(validator):
    with pytest.raises(FormValidationError):
        validator.validate_create(
            {
                "org_id": 10,
                "name": "Bad",
                "permissions": [{"resource_type": "nope", "actions": ["read"]}],
            }
        )


def test_validate_create_duplicate_resource_type_rejected(validator):
    # Two entries for the same resource_type would violate the
    # (role, resource_type) unique constraint at write time — reject at 400
    # rather than surfacing an IntegrityError (500).
    with pytest.raises(FormValidationError) as exc:
        validator.validate_create(
            {
                "org_id": 10,
                "name": "Dup Resource",
                "permissions": [
                    {"resource_type": "secrets", "actions": ["read"]},
                    {"resource_type": "secrets", "actions": ["update"]},
                ],
            }
        )
    assert any(e["field"] == "permissions[1].resource_type" for e in exc.value.errors)


def test_validate_update_duplicate_resource_type_rejected(validator):
    with pytest.raises(FormValidationError) as exc:
        validator.validate_update(
            {
                "permissions": [
                    {"resource_type": "flows", "actions": ["read"]},
                    {"resource_type": "flows", "actions": ["create"]},
                ]
            }
        )
    assert any("resource_type" in e["field"] for e in exc.value.errors)


def test_validate_update_partial_only_present_keys(validator):
    cleaned = validator.validate_update({"description": "new desc"})
    assert cleaned == {"description": "new desc"}


def test_validate_update_rejects_reserved_name(validator):
    with pytest.raises(FormValidationError):
        validator.validate_update({"name": "Viewer"})


def test_granting_org_create_rejected_as_platform_action(validator):
    # organizations.create is platform-level (superadmin-only) — not grantable.
    with pytest.raises(FormValidationError) as exc:
        validator.validate_create(
            {
                "org_id": 10,
                "name": "Bad",
                "permissions": [
                    {"resource_type": "organizations", "actions": ["create"]}
                ],
            }
        )
    reasons = " ".join(e["reason"] for e in exc.value.errors)
    assert "platform" in reasons.lower()


def test_granting_org_read_update_still_allowed(validator):
    cleaned = validator.validate_create(
        {
            "org_id": 10,
            "name": "Org Manager",
            "permissions": [
                {"resource_type": "organizations", "actions": ["read", "update"]}
            ],
        }
    )
    assert cleaned["permissions"] == [
        {
            "resource_type": "organizations",
            "bitmask": int(Permission.READ | Permission.UPDATE),
        }
    ]
