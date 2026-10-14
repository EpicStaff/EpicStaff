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


def test_granting_flows_run_is_accepted(validator):
    cleaned = validator.validate_create(
        {
            "org_id": 10,
            "name": "Flow Runner",
            "permissions": [{"resource_type": "flows", "actions": ["read", "run"]}],
        }
    )
    assert cleaned["permissions"] == [
        {"resource_type": "flows", "bitmask": int(Permission.READ | Permission.RUN)}
    ]


def test_granting_run_outside_flows_is_rejected(validator):
    with pytest.raises(FormValidationError) as exc:
        validator.validate_create(
            {
                "org_id": 10,
                "name": "Bad Runner",
                "permissions": [{"resource_type": "agents", "actions": ["run"]}],
            }
        )
    assert any("agents" in e["field"] for e in exc.value.errors)
