"""A PythonCode's `execution_timeout` reaches every copy of the code and the payload that
runs it.

Invariant: copying a graph or a python tool, restoring a saved graph version, and
converting the code into the `PythonCodeData` crew and the sandbox run all carry the code's
own timeout in seconds, never the deployment default. A path that silently fell back to
the default would let user code run longer, or shorter, than its author set.
"""

import pytest

from tables.graph_versioning.services import GraphVersioningService
from tables.models import Edge, PythonCode, PythonCodeTool, StartNode
from tables.services.converter_service import ConverterService
from tables.services.copy_services.graph_copy_service import GraphCopyService
from tables.services.copy_services.python_code_tool_copy_service import (
    PythonCodeToolCopyService,
)
from tables.services.session_manager_service import SessionManagerService
from tests.python_code_slots import PYTHON_CODE_SLOT_IDS, PYTHON_CODE_SLOTS

# Distinct from the default, so a path that drops the value and falls back fails.
STORED_SECONDS = 7
DEFAULT_SECONDS = 45


@pytest.fixture(autouse=True)
def execution_timeout_limits(settings):
    settings.MAX_EXECUTION_TIMEOUT_SECONDS = 600
    settings.DEFAULT_EXECUTION_TIMEOUT_SECONDS = DEFAULT_SECONDS


@pytest.fixture(params=PYTHON_CODE_SLOTS, ids=PYTHON_CODE_SLOT_IDS)
def slot(request):
    return request.param


def _python_code(seconds: int = STORED_SECONDS) -> PythonCode:
    return PythonCode.objects.create(code="def main(): return 1", execution_timeout=seconds)


@pytest.fixture
def node(slot, graph):
    return slot.create(graph, _python_code())


@pytest.mark.django_db
def test_graph_copy_keeps_the_execution_timeout(slot, graph, node):
    copied_graph = GraphCopyService().copy(graph, name="copied")

    copied_code = slot.python_code_of(slot.only_node_in(copied_graph))
    assert copied_code.pk != slot.python_code_of(node).pk
    assert copied_code.execution_timeout == STORED_SECONDS


@pytest.mark.django_db
def test_python_tool_copy_keeps_the_execution_timeout(default_org):
    tool = PythonCodeTool.objects.create(
        name="execution-timeout-tool",
        description="tool",
        python_code=_python_code(),
        org=default_org,
    )

    copied_tool = PythonCodeToolCopyService().copy(tool)

    assert copied_tool.python_code_id != tool.python_code_id
    assert copied_tool.python_code.execution_timeout == STORED_SECONDS


@pytest.mark.django_db
def test_version_restore_brings_back_the_execution_timeout(slot, graph, node, regular_user):
    versioning = GraphVersioningService()
    version = versioning.save_version(graph=graph, name="with-timeout")
    PythonCode.objects.filter(pk=slot.python_code_of(node).pk).update(execution_timeout=99)
    graph.refresh_from_db()

    versioning.restore_version(version, expected_save_version=graph.save_version, user=regular_user)

    restored_code = slot.python_code_of(slot.only_node_in(graph))
    assert restored_code.execution_timeout == STORED_SECONDS


@pytest.mark.django_db
@pytest.mark.parametrize("seconds", [3, STORED_SECONDS, 600])
def test_converter_puts_the_execution_timeout_into_the_payload(seconds):
    python_code_data = ConverterService().convert_python_code_to_pydantic(_python_code(seconds))

    assert python_code_data.execution_timeout == seconds


@pytest.mark.django_db
def test_session_schema_carries_the_execution_timeout(slot, graph, node):
    # _build_graph_data needs a resolvable entrypoint; wire start -> node.
    start_node = StartNode.objects.create(graph=graph, variables={})
    Edge.objects.create(graph=graph, start_node_id=start_node.id, end_node_id=node.id)

    graph_data = SessionManagerService()._build_graph_data(graph, None, None)

    [node_data] = getattr(graph_data, slot.session_list_key)
    assert getattr(node_data, slot.code_field).execution_timeout == STORED_SECONDS
