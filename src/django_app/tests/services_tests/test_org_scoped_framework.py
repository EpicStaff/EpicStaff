from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rest_framework.exceptions import NotFound

from rbac.scoping.mixins import (
    OrgScopedChildViewSetMixin,
    OrgScopedViewSetMixin,
)


class _Base:
    """Stand-in for the DRF GenericViewSet base in the MRO."""

    def __init__(self, base_qs):
        self._base_qs = base_qs

    def get_queryset(self):
        return self._base_qs

    def perform_update(self, serializer):
        serializer.save()


class _TopView(OrgScopedViewSetMixin, _Base):
    pass


class _ChildView(OrgScopedChildViewSetMixin, _Base):
    org_filter_path = "graph__org_id"


def _make(view, org_id=7):
    view.request = SimpleNamespace(user=SimpleNamespace(is_superadmin=False))
    view.kwargs = {}
    view._org_context = MagicMock()
    view._org_context.resolve.return_value = org_id
    return view


def test_top_level_queryset_filters_by_org():
    qs = MagicMock()
    view = _make(_TopView(qs))
    view.get_queryset()
    qs.filter.assert_called_once_with(org_id=7)


def test_child_queryset_filters_by_parent_path():
    qs = MagicMock()
    view = _make(_ChildView(qs))
    view.get_queryset()
    qs.filter.assert_called_once_with(**{"graph__org_id": 7})


def test_perform_create_stamps_org_and_created_by():
    view = _make(_TopView(MagicMock()))
    serializer = MagicMock()
    view.perform_create(serializer)
    serializer.save.assert_called_once_with(org_id=7, created_by=view.request.user)


def test_active_org_id_is_cached_per_request():
    view = _make(_TopView(MagicMock()))
    view.get_active_org_id()
    view.get_active_org_id()
    assert view._org_context.resolve.call_count == 1


def _serializer_with_parent_in_org(org_id):
    serializer = MagicMock()
    serializer.validated_data = {"graph": SimpleNamespace(org_id=org_id)}
    return serializer


def test_child_perform_update_saves_when_parent_is_in_active_org():
    view = _make(_ChildView(MagicMock()), org_id=7)
    serializer = _serializer_with_parent_in_org(7)
    view.perform_update(serializer)
    serializer.save.assert_called_once_with()


def test_child_perform_update_rejects_parent_in_other_org():
    view = _make(_ChildView(MagicMock()), org_id=7)
    serializer = _serializer_with_parent_in_org(8)
    with pytest.raises(NotFound):
        view.perform_update(serializer)
    serializer.save.assert_not_called()


def test_child_perform_update_without_parent_in_payload_saves():
    view = _make(_ChildView(MagicMock()), org_id=7)
    serializer = MagicMock()
    serializer.validated_data = {}
    view.perform_update(serializer)
    serializer.save.assert_called_once_with()
