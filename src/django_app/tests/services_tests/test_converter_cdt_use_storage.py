import pytest

from tables.models import ClassificationDecisionTableNode, PythonCode, Graph
from tables.models.rbac_models import Organization
from tables.services.converter_service import ConverterService


@pytest.fixture
def converter() -> ConverterService:
    return ConverterService()


@pytest.mark.django_db
def test_convert_cdt_node_pre_and_post_use_storage_true_populates_both_blocks(
    converter,
):
    org = Organization.objects.create(name="Org CDT A")
    graph = Graph.objects.create(name="cdt-g1", org=org)

    pre_code = PythonCode.objects.create(code="def main(**kw): return kw")
    post_code = PythonCode.objects.create(code="def main(**kw): return kw")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        pre_python_code=pre_code,
        post_python_code=post_code,
        pre_use_storage=True,
        post_use_storage=True,
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
    assert any(
        path == "sessions/7/" for path in data.post_python_code.storage_allowed_paths
    )


@pytest.mark.django_db
def test_convert_cdt_node_pre_use_storage_true_post_false_populates_only_pre_block(
    converter,
):
    org = Organization.objects.create(name="Org CDT D")
    graph = Graph.objects.create(name="cdt-g4", org=org)

    pre_code = PythonCode.objects.create(code="def main(**kw): return kw")
    post_code = PythonCode.objects.create(code="def main(**kw): return kw")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        pre_python_code=pre_code,
        post_python_code=post_code,
        pre_use_storage=True,
        post_use_storage=False,
    )

    data = converter.convert_classification_decision_table_node_to_pydantic(
        node, graph_id=graph.pk, session_id=7
    )

    assert data.pre_python_code.use_storage is True
    assert data.pre_python_code.org_id == org.pk
    assert any(
        path == "sessions/7/" for path in data.pre_python_code.storage_allowed_paths
    )

    assert data.post_python_code.use_storage is False
    assert data.post_python_code.storage_allowed_paths is None
    assert data.post_python_code.storage_org_prefix is None


@pytest.mark.django_db
def test_convert_cdt_node_pre_use_storage_false_post_true_populates_only_post_block(
    converter,
):
    org = Organization.objects.create(name="Org CDT E")
    graph = Graph.objects.create(name="cdt-g5", org=org)

    pre_code = PythonCode.objects.create(code="def main(**kw): return kw")
    post_code = PythonCode.objects.create(code="def main(**kw): return kw")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        pre_python_code=pre_code,
        post_python_code=post_code,
        pre_use_storage=False,
        post_use_storage=True,
    )

    data = converter.convert_classification_decision_table_node_to_pydantic(
        node, graph_id=graph.pk, session_id=7
    )

    assert data.pre_python_code.use_storage is False
    assert data.pre_python_code.storage_allowed_paths is None
    assert data.pre_python_code.storage_org_prefix is None

    assert data.post_python_code.use_storage is True
    assert data.post_python_code.org_id == org.pk
    assert any(
        path == "sessions/7/" for path in data.post_python_code.storage_allowed_paths
    )


@pytest.mark.django_db
def test_convert_cdt_node_pre_and_post_use_storage_false_leaves_both_blocks_without_storage(
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
        pre_use_storage=False,
        post_use_storage=False,
    )

    data = converter.convert_classification_decision_table_node_to_pydantic(
        node, graph_id=graph.pk, session_id=7
    )

    assert data.pre_python_code.use_storage is False
    assert data.post_python_code.use_storage is False
    assert data.pre_python_code.storage_allowed_paths is None
    assert data.post_python_code.storage_allowed_paths is None


@pytest.mark.django_db
def test_convert_cdt_node_pre_and_post_use_storage_true_without_graph_id_keeps_flag_but_resolves_no_paths(
    converter,
):
    org = Organization.objects.create(name="Org CDT C")
    graph = Graph.objects.create(name="cdt-g3", org=org)
    pre_code = PythonCode.objects.create(code="def main(**kw): return kw")
    post_code = PythonCode.objects.create(code="def main(**kw): return kw")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        pre_python_code=pre_code,
        post_python_code=post_code,
        pre_use_storage=True,
        post_use_storage=True,
    )

    # graph_id explicitly omitted — storage resolution must not run for
    # either block even though both flags are True, mirroring the
    # PythonNode converter contract.
    data = converter.convert_classification_decision_table_node_to_pydantic(
        node, graph_id=None, session_id=None
    )

    assert data.pre_python_code.use_storage is True
    assert data.pre_python_code.storage_allowed_paths is None
    assert data.pre_python_code.org_id is None

    assert data.post_python_code.use_storage is True
    assert data.post_python_code.storage_allowed_paths is None
    assert data.post_python_code.org_id is None
