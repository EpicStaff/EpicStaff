"""Storage a classification decision table's pre and post code slots get from the converter.

Both slots always get the session's storage scope; what each may do to the flow's files
is the grant of its own slot.
"""

import pytest

from rbac.models import Organization
from tables.models import ClassificationDecisionTableNode, Graph, PythonCode
from tables.services.converter_service import ConverterService
from utils.graph_utils import NodeNameResolver


@pytest.fixture
def converter() -> ConverterService:
    return ConverterService()


def _code() -> PythonCode:
    return PythonCode.objects.create(code="def main(**kw): return kw")


def _convert(converter, node, graph_id, session_id):
    return converter.convert_classification_decision_table_node_to_pydantic(
        node,
        resolver=NodeNameResolver(graph_id=node.graph_id),
        graph_id=graph_id,
        session_id=session_id,
    )


@pytest.mark.django_db
def test_both_slots_get_the_session_scope_even_with_no_box_ticked(converter):
    org = Organization.objects.create(name="Org CDT A")
    graph = Graph.objects.create(name="cdt-g1", org=org)
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph, pre_python_code=_code(), post_python_code=_code()
    )

    data = _convert(converter, node, graph.pk, session_id=7)

    for slot in (data.pre_python_code, data.post_python_code):
        assert slot.use_storage is True
        assert slot.org_id == org.pk
        assert slot.storage_org_prefix == f"org_{org.pk}"
        assert slot.storage_allowed_paths == ["sessions/7/"]
        assert slot.storage_grant.model_dump() == {"read": False, "write": False, "delete": False}


@pytest.mark.django_db
def test_each_slot_carries_the_grant_of_its_own_boxes(converter):
    graph = Graph.objects.create(name="cdt-g2", org=Organization.objects.create(name="Org CDT B"))
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        pre_python_code=_code(),
        post_python_code=_code(),
        pre_storage_grant_read=True,
        post_storage_grant_write=True,
        post_storage_grant_delete=True,
    )

    data = _convert(converter, node, graph.pk, session_id=7)

    assert data.pre_python_code.storage_grant.model_dump() == {
        "read": True,
        "write": False,
        "delete": False,
    }
    assert data.post_python_code.storage_grant.model_dump() == {
        "read": False,
        "write": True,
        "delete": True,
    }


@pytest.mark.django_db
def test_a_slot_without_code_is_not_converted(converter):
    graph = Graph.objects.create(name="cdt-g3", org=Organization.objects.create(name="Org CDT C"))
    node = ClassificationDecisionTableNode.objects.create(graph=graph, pre_python_code=_code())

    data = _convert(converter, node, graph.pk, session_id=7)

    assert data.pre_python_code.use_storage is True
    assert data.post_python_code is None


@pytest.mark.django_db
def test_without_graph_id_the_slots_resolve_no_paths(converter):
    graph = Graph.objects.create(name="cdt-g4", org=Organization.objects.create(name="Org CDT D"))
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph, pre_python_code=_code(), post_python_code=_code()
    )

    data = _convert(converter, node, graph_id=None, session_id=None)

    for slot in (data.pre_python_code, data.post_python_code):
        assert slot.storage_allowed_paths is None
        assert slot.storage_org_prefix is None
        assert slot.org_id is None
