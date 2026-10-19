import pytest

from rbac.models.enums import Permission
from rbac.exceptions import FormValidationError
from rbac.validation.role import RoleValidationService


@pytest.fixture
def validator():
    return RoleValidationService()


def test_validate_create_happy_path(validator):
    cleaned = validator.validate_create(
        {
            "org_id": 10,
            "name": "  Billing Manager ",
            "description": "manage billing",
            "permissions": [{"resource_type": "secrets", "actions": ["read", "use"]}],
        }
    )
    assert cleaned["org_id"] == 10
    assert cleaned["name"] == "Billing Manager"  # trimmed
    assert cleaned["permissions"] == [
        {
            "resource_type": "secrets",
            "bitmask": int(Permission.READ | Permission.USE),
        }
    ]


def test_validate_create_empty_permissions_allowed(validator):
    cleaned = validator.validate_create({"org_id": 10, "name": "No Access"})
    assert cleaned["permissions"] == []


def test_validate_update_partial_only_present_keys(validator):
    cleaned = validator.validate_update({"description": "new desc"})
    assert cleaned == {"description": "new desc"}


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


def _create(**fields):
    return lambda validator: validator.validate_create({"org_id": 10, "name": "Bad", **fields})


@pytest.mark.parametrize(
    ("call", "field_fragment", "reason_fragment"),
    [
        (_create(name="Org Admin"), "name", None),
        (lambda validator: validator.validate_update({"name": "Viewer"}), "name", None),
        (_create(name="   "), "name", None),
        (lambda validator: validator.validate_create({"name": "X"}), "org_id", None),
        # secrets has no "export" among its applicable actions.
        (_create(permissions=[{"resource_type": "secrets", "actions": ["export"]}]), "secrets", None),
        (_create(permissions=[{"resource_type": "nope", "actions": ["read"]}]), "resource_type", None),
        # Two entries for one resource_type would hit the (role, resource_type) unique
        # constraint at write time: a 400 here instead of a 500 there.
        (
            _create(permissions=[{"resource_type": "secrets", "actions": ["read"]},
                                 {"resource_type": "secrets", "actions": ["use"]}]),
            "permissions[1].resource_type", None,
        ),
        (
            lambda validator: validator.validate_update({"permissions": [
                {"resource_type": "flows", "actions": ["read"]},
                {"resource_type": "flows", "actions": ["create"]},
            ]}),
            "resource_type", None,
        ),
        # organizations.create is platform-level (superadmin-only), never grantable.
        (_create(permissions=[{"resource_type": "organizations", "actions": ["create"]}]), None, "platform"),
    ],
    ids=[
        "reserved-name", "reserved-name-on-update", "blank-name", "no-org", "inapplicable-action",
        "unknown-resource", "duplicate-resource", "duplicate-resource-on-update", "platform-action",
    ],
)
def test_invalid_role_is_rejected_naming_the_field(validator, call, field_fragment, reason_fragment):
    with pytest.raises(FormValidationError) as exc:
        call(validator)

    if field_fragment:
        assert any(field_fragment in error["field"] for error in exc.value.errors), exc.value.errors
    if reason_fragment:
        assert reason_fragment in " ".join(error["reason"] for error in exc.value.errors).lower()


# ---- the audit history limit inside the audit entry ----


def _audit(**extra):
    return {"resource_type": "audit", "actions": ["read"], **extra}


def test_create_lifts_the_audit_limit_out_of_the_entry(validator):
    cleaned = validator.validate_create(
        {"org_id": 1, "name": "Auditor", "permissions": [_audit(audit_history_days=30)]}
    )

    assert cleaned["audit_history_days"] == 30
    assert cleaned["permissions"] == [{"resource_type": "audit", "bitmask": int(Permission.READ)}]


def test_create_without_a_limit_is_unlimited(validator):
    cleaned = validator.validate_create({"org_id": 1, "name": "Auditor", "permissions": [_audit()]})

    assert cleaned["audit_history_days"] == 0


def test_update_without_permissions_carries_no_limit(validator):
    """So the service leaves the stored limit untouched."""
    assert validator.validate_update({"name": "Renamed"}) == {"name": "Renamed"}


def test_update_with_permissions_always_carries_the_limit(validator):
    cleaned = validator.validate_update({"permissions": [_audit()]})

    assert cleaned["audit_history_days"] == 0


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"audit_history_days": 30}, "audit_history_days"),
        (
            {"permissions": [{"resource_type": "flows", "actions": ["read"], "audit_history_days": 1}]},
            "permissions[0].audit_history_days",
        ),
        (
            {"permissions": [{"resource_type": "audit", "actions": [], "audit_history_days": 1}]},
            "permissions[0].audit_history_days",
        ),
    ],
    ids=["top-level", "non-audit entry", "no read or export"],
)
def test_misplaced_or_unusable_limit_is_rejected(validator, data, field):
    with pytest.raises(FormValidationError) as error:
        validator.validate_update(data)

    assert field in [entry["field"] for entry in error.value.errors]
