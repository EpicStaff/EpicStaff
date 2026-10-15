"""No API or import/export serializer exposes the soft-delete state.

Only DeleteService (and restore) write `active`, `soft_deleted_at` and
`soft_delete_batch`. A serializer that exposes them lets a client or an import
file bin a row past DeleteService, or break the consistency check (a 500).
"""

import importlib
import pkgutil

import pytest
from rest_framework import serializers

from tables.models.base_models import SOFT_DELETE_FIELD_NAMES, SoftDeleteFields
from tables.models.graph_models import Condition, ConditionGroup, DecisionTableNode
from tables.services.graph_bulk_save_service.saveables import DecisionTableNodeSaveable

_SERIALIZER_PACKAGES = (
    "tables.serializers",
    "agents.serializers",
    "tables.import_export.serializers",
    "tables.graph_versioning",
)


def _import_serializer_modules():
    for package_name in _SERIALIZER_PACKAGES:
        package = importlib.import_module(package_name)
        for module in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
            importlib.import_module(module.name)


def _all_subclasses(cls):
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _all_subclasses(subclass)


def _soft_delete_model_serializers():
    _import_serializer_modules()
    found = {
        serializer_class
        for serializer_class in _all_subclasses(serializers.ModelSerializer)
        if getattr(getattr(serializer_class, "Meta", None), "model", None) is not None
        and issubclass(serializer_class.Meta.model, SoftDeleteFields)
        and serializer_class.__module__.startswith(_SERIALIZER_PACKAGES)
    }
    return sorted(found, key=lambda serializer_class: f"{serializer_class.__module__}.{serializer_class.__name__}")


@pytest.mark.parametrize(
    "serializer_class",
    _soft_delete_model_serializers(),
    ids=lambda serializer_class: f"{serializer_class.__module__.rsplit('.', 1)[-1]}.{serializer_class.__name__}",
)
def test_serializer_does_not_expose_soft_delete_fields(serializer_class):
    exposed = set(serializer_class().get_fields()) & set(SOFT_DELETE_FIELD_NAMES)

    assert not exposed, f"{serializer_class.__module__}.{serializer_class.__name__} exposes {sorted(exposed)}"


@pytest.mark.django_db
def test_bulk_save_ignores_soft_delete_state_in_condition_groups(graph):
    # Bulk save builds condition groups and conditions straight from the
    # request, past any serializer, so it filters the fields itself.
    node = DecisionTableNode.objects.create(graph=graph, node_name="decision")
    soft_delete_state = {"active": False, "soft_deleted_at": "2026-01-01T00:00:00Z"}

    created_groups = DecisionTableNodeSaveable._create_condition_groups(
        node,
        [
            {
                "group_name": "group",
                "order": 0,
                **soft_delete_state,
                "conditions": [{"condition_name": "c", "condition": "x > 1", **soft_delete_state}],
            }
        ],
    )

    group = ConditionGroup.all_objects.get(pk=created_groups[0].pk)
    assert group.active is True and group.soft_deleted_at is None
    condition = Condition.all_objects.get(condition_group=group)
    assert condition.active is True and condition.soft_deleted_at is None
