"""Every importable entity type is either gated by an export permission or exempt from it.

A type added to ENTITY_RESOURCE_MAP whose resource offers `export` would otherwise
be bundled into every flow export without any permission check.
"""

import pytest

from rbac.access.catalog import RESOURCE_TYPE_METADATA
from tables.import_export.permissions import (
    ENTITY_RESOURCE_MAP,
    EXPORT_EXEMPT_TYPES,
    EXPORT_RESOURCE_MAP,
)

RESOURCES_OFFERING_EXPORT = {
    entry["code"] for entry in RESOURCE_TYPE_METADATA if "export" in entry["applicable_actions"]
}


def test_every_type_on_an_exportable_resource_is_gated_or_exempt():
    undecided = {
        entity_type
        for entity_type, resource in ENTITY_RESOURCE_MAP.items()
        if resource.value in RESOURCES_OFFERING_EXPORT
        and entity_type not in EXPORT_RESOURCE_MAP
        and entity_type not in EXPORT_EXEMPT_TYPES
    }

    assert not undecided, f"Decide whether export gates these types: {sorted(undecided)}"


def test_a_type_is_never_both_gated_and_exempt():
    assert not set(EXPORT_RESOURCE_MAP) & EXPORT_EXEMPT_TYPES


@pytest.mark.parametrize("entity_type", sorted(EXPORT_RESOURCE_MAP))
def test_gated_types_use_the_resource_their_endpoint_uses(entity_type):
    assert EXPORT_RESOURCE_MAP[entity_type] == ENTITY_RESOURCE_MAP[entity_type]
    assert EXPORT_RESOURCE_MAP[entity_type].value in RESOURCES_OFFERING_EXPORT
