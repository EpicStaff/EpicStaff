from tables.models.rbac_models.rbac_enums import ResourceType
from tables.services.rbac.permission_catalog import (
    RESOURCE_TYPE_METADATA,
    applicable_actions_for,
)


def test_surfaces_resource_type_exists():
    assert ResourceType.SURFACES.value == "surfaces"


def test_surfaces_in_catalog_workspace_group():
    entry = next(e for e in RESOURCE_TYPE_METADATA if e["code"] == "surfaces")
    assert entry["group"] == "workspace"
    assert entry["applicable_actions"] == ["create", "read", "update", "delete"]


def test_surfaces_applicable_actions_helper():
    assert applicable_actions_for("surfaces") == ["create", "read", "update", "delete"]
