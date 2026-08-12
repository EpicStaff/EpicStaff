"""
Enable Storage for CDT pre/post computation (review comment on EST-3346).

A single `use_storage` flag on `ClassificationDecisionTableNode` gates storage
access for BOTH the pre- and post-computation `PythonCode` blocks, resolved
from the same `graph_id`/`session_id` — mirrors the pattern already covered
for `PythonNode` in `test_converter_service_org_id.py`.
"""

import pytest

from tables.models import ClassificationDecisionTableNode, PythonCode, Graph
from tables.models.rbac_models import Organization
from tables.services.converter_service import ConverterService


@pytest.fixture
def converter() -> ConverterService:
    return ConverterService()


@pytest.mark.django_db
def test_convert_cdt_node_use_storage_true_populates_both_blocks(converter):
    org = Organization.objects.create(name="Org CDT A")
    graph = Graph.objects.create(name="cdt-g1", org=org)

    pre_code = PythonCode.objects.create(code="def main(**kw): return kw")
    post_code = PythonCode.objects.create(code="def main(**kw): return kw")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        pre_python_code=pre_code,
        post_python_code=post_code,
        use_storage=True,
    )

    data = converter.convert_classification_decision_table_node_to_pydantic(
        node, graph_id=graph.pk, session_id=7
    )

    assert data.pre_python_code.use_storage is True
    assert data.post_python_code.use_storage is True
    assert data.pre_python_code.org_id == org.pk
    assert data.post_python_code.org_id == org.pk
    assert (
        data.pre_python_code.storage_allowed_paths
        == data.post_python_code.storage_allowed_paths
    )
    assert any(
        path == "sessions/7/" for path in data.pre_python_code.storage_allowed_paths
    )


@pytest.mark.django_db
def test_convert_cdt_node_use_storage_false_leaves_both_blocks_without_storage(
    converter,
):
    org = Organization.objects.create(name="Org CDT B")
    graph = Graph.objects.create(name="cdt-g2", org=org)

    pre_code = PythonCode.objects.create(code="def main(**kw): return kw")
    post_code = PythonCode.objects.create(code="def main(**kw): return kw")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        pre_python_code=pre_code,
        post_python_code=post_code,
        use_storage=False,
    )

    data = converter.convert_classification_decision_table_node_to_pydantic(
        node, graph_id=graph.pk, session_id=7
    )

    assert data.pre_python_code.use_storage is False
    assert data.post_python_code.use_storage is False
    assert data.pre_python_code.storage_allowed_paths is None
    assert data.post_python_code.storage_allowed_paths is None


@pytest.mark.django_db
def test_convert_cdt_node_use_storage_true_without_graph_id_is_noop(converter):
    org = Organization.objects.create(name="Org CDT C")
    graph = Graph.objects.create(name="cdt-g3", org=org)
    pre_code = PythonCode.objects.create(code="def main(**kw): return kw")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        pre_python_code=pre_code,
        use_storage=True,
    )

    # graph_id explicitly omitted — storage resolution must not run even
    # though use_storage=True, mirroring the PythonNode converter contract.
    data = converter.convert_classification_decision_table_node_to_pydantic(
        node, graph_id=None, session_id=None
    )

    assert data.pre_python_code.use_storage is True
    assert data.pre_python_code.storage_allowed_paths is None
    assert data.pre_python_code.org_id is None
