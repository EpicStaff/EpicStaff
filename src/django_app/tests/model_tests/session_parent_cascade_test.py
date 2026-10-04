from unittest.mock import patch

import pytest

from tables.models.session_models import Session


def _make_session(graph, parent: Session | None = None) -> Session:
    return Session.objects.create(
        graph=graph,
        status=Session.SessionStatus.PENDING,
        variables={},
        parent_session=parent,
    )


@pytest.mark.django_db
def test_deleting_parent_session_deletes_children_and_grandchildren(graph):
    parent = _make_session(graph)
    child = _make_session(graph, parent=parent)
    sibling = _make_session(graph, parent=parent)
    grandchild = _make_session(graph, parent=child)
    unrelated_root = _make_session(graph)
    subtree_ids = [parent.id, child.id, sibling.id, grandchild.id]

    parent.delete()

    assert not Session.objects.filter(id__in=subtree_ids).exists()
    assert Session.objects.filter(id=unrelated_root.id).exists()


@pytest.mark.django_db
def test_deleting_child_session_leaves_parent_and_siblings(graph):
    parent = _make_session(graph)
    child = _make_session(graph, parent=parent)
    sibling = _make_session(graph, parent=parent)
    grandchild = _make_session(graph, parent=child)
    removed_ids = [child.id, grandchild.id]

    child.delete()

    assert not Session.objects.filter(id__in=removed_ids).exists()
    assert Session.objects.filter(id=parent.id).exists()
    sibling.refresh_from_db()
    assert sibling.parent_session_id == parent.id


@pytest.mark.django_db
def test_no_session_is_left_as_a_parentless_orphan_after_parent_delete(graph):
    parent = _make_session(graph)
    _make_session(graph, parent=_make_session(graph, parent=parent))

    parent.delete()

    assert not Session.objects.filter(graph=graph, parent_session_id=None).exists()


@pytest.mark.django_db
def test_deleting_parent_session_schedules_stop_for_cascaded_children(
    graph, django_capture_on_commit_callbacks
):
    parent = _make_session(graph)
    child = _make_session(graph, parent=parent)
    grandchild = _make_session(graph, parent=child)
    subtree_ids = {parent.id, child.id, grandchild.id}

    with patch(
        "tables.signals.session_signals.SessionManagerService.stop_session"
    ) as mock_stop_session:
        with django_capture_on_commit_callbacks(execute=True):
            parent.delete()

    stopped_session_ids = {
        call.kwargs["session_id"] for call in mock_stop_session.call_args_list
    }
    assert stopped_session_ids == subtree_ids
