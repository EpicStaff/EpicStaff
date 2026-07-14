from types import SimpleNamespace
from unittest.mock import MagicMock

from tables.views.mixins import (
    OrgScopedChildViewSetMixin,
    OrgScopedViewSetMixin,
)


class _Base:
    """Stand-in for the DRF GenericViewSet base in the MRO."""

    def __init__(self, base_qs):
        self._base_qs = base_qs

    def get_queryset(self):
        return self._base_qs


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
