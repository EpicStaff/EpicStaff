"""Import files made before the storage switch was removed.

Such a file carries `use_storage` on its Python, Webhook trigger and Classification decision
table nodes (`pre_use_storage` and `post_use_storage` per code slot). The migration that
introduced grants ticked every box on every existing node, so a node whose switch was off
holds ticked boxes in the file; importing it must not give that node access to the flow's
files. A switch that is on, or missing, leaves the usual rules: a missing box reads as
ticked, then is limited to what the importing user may hand out.
"""

import pytest

from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    PythonNode,
    WebhookTriggerNode,
)
from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

BOXES = ("storage_grant_read", "storage_grant_write", "storage_grant_delete")
SWITCH_STATES = [
    pytest.param(False, (False, False, False), id="switch-off-clears-every-box"),
    pytest.param(True, (True, True, True), id="switch-on-keeps-the-boxes"),
    pytest.param(None, (True, True, True), id="no-switch-keeps-the-boxes"),
]


def _code() -> PythonCode:
    return PythonCode.objects.create(code="def main(**kwargs): ...", entrypoint="main")


@pytest.fixture
def source_graph(acme):
    graph = Graph.objects.create(name="retired-switch-source", org=acme)
    ticked = dict.fromkeys(BOXES, True)
    PythonNode.objects.create(graph=graph, python_code=_code(), **ticked)
    WebhookTriggerNode.objects.create(graph=graph, node_name="hook", python_code=_code(), **ticked)
    ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name="table",
        pre_python_code=_code(),
        post_python_code=_code(),
        **{f"{slot}_{box}": True for slot in ("pre", "post") for box in BOXES},
    )
    return graph


def _write_old_switches(data, *, code_node_switch=None, pre_switch=None, post_switch=None):
    """Add the retired switches to every node entry of an export, as an old file has them.

    A switch of None is left out of the file.
    """
    if isinstance(data, list):
        for item in data:
            _write_old_switches(
                item,
                code_node_switch=code_node_switch,
                pre_switch=pre_switch,
                post_switch=post_switch,
            )
    elif isinstance(data, dict):
        if "storage_grant_read" in data and code_node_switch is not None:
            data["use_storage"] = code_node_switch
        if "pre_storage_grant_read" in data:
            for name, switch in (("pre_use_storage", pre_switch), ("post_use_storage", post_switch)):
                if switch is not None:
                    data[name] = switch
        for value in data.values():
            _write_old_switches(
                value,
                code_node_switch=code_node_switch,
                pre_switch=pre_switch,
                post_switch=post_switch,
            )


def _drop_boxes(data):
    if isinstance(data, list):
        for item in data:
            _drop_boxes(item)
    elif isinstance(data, dict):
        for box in BOXES:
            data.pop(box, None)
        for value in data.values():
            _drop_boxes(value)


def _boxes(node, prefix=""):
    return tuple(getattr(node, f"{prefix}{box}") for box in BOXES)


def _import_graph(export_data, org, user) -> Graph:
    id_mapper, _ = ImportService(entity_registry).import_data(
        export_data, EntityType.GRAPH, settings=ImportSettings(), org_id=org.id, user=user
    )
    return Graph.objects.get(pk=id_mapper.get_created_ids(EntityType.GRAPH)[0])


@pytest.fixture
def full_export(source_graph):
    def _export(**switches):
        data = (
            ExportService(entity_registry)
            .export_entities(EntityType.GRAPH, [source_graph.id], policy=UNRESTRICTED_EXPORT_POLICY)
            .data
        )
        _write_old_switches(data, **switches)
        return data

    return _export


def _partial_export(graph, org, entity_type, node_ids):
    export = GraphPartialExportService(entity_registry).export(
        [NodeRef(entity_type=entity_type, node_id=node_id) for node_id in node_ids],
        org_id=org.id,
        policy=UNRESTRICTED_EXPORT_POLICY,
    )
    assert not export.has_errors, export.errors
    return export.data


@pytest.mark.django_db
@pytest.mark.parametrize(("switch", "expected"), SWITCH_STATES)
def test_full_import_of_python_and_webhook_nodes(acme, admin_acme, full_export, switch, expected):
    graph = _import_graph(full_export(code_node_switch=switch), acme, admin_acme)

    assert _boxes(graph.python_node_list.get()) == expected
    assert _boxes(graph.webhook_trigger_node_list.get()) == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("pre_switch", "post_switch", "expected_pre", "expected_post"),
    [
        pytest.param(False, True, (False,) * 3, (True,) * 3, id="only-pre-off"),
        pytest.param(True, False, (True,) * 3, (False,) * 3, id="only-post-off"),
        pytest.param(False, False, (False,) * 3, (False,) * 3, id="both-off"),
        pytest.param(None, None, (True,) * 3, (True,) * 3, id="neither-present"),
    ],
)
def test_full_import_clears_only_the_code_slot_whose_switch_is_off(
    acme, admin_acme, full_export, pre_switch, post_switch, expected_pre, expected_post
):
    data = full_export(pre_switch=pre_switch, post_switch=post_switch)

    node = _import_graph(data, acme, admin_acme).classification_decision_table_node_list.get()

    assert _boxes(node, "pre_") == expected_pre
    assert _boxes(node, "post_") == expected_post


@pytest.mark.django_db
def test_a_missing_box_with_the_switch_on_is_still_limited_to_the_users_permissions(
    acme, member_only, full_export
):
    data = full_export(code_node_switch=True)
    _drop_boxes(data)

    graph = _import_graph(data, acme, member_only)

    # The Member role may read, create and update files but not delete them.
    assert _boxes(graph.python_node_list.get()) == (True, True, False)


@pytest.mark.django_db
@pytest.mark.parametrize(("switch", "expected"), SWITCH_STATES)
def test_partial_import_of_python_and_webhook_nodes(
    acme, admin_acme, source_graph, switch, expected
):
    data = _partial_export(
        source_graph,
        acme,
        EntityType.PYTHON_NODE,
        [source_graph.python_node_list.get().id],
    )
    webhook_data = _partial_export(
        source_graph,
        acme,
        EntityType.WEBHOOK_TRIGGER_NODE,
        [source_graph.webhook_trigger_node_list.get().id],
    )
    data[EntityType.WEBHOOK_TRIGGER_NODE] = webhook_data[EntityType.WEBHOOK_TRIGGER_NODE]
    _write_old_switches(data, code_node_switch=switch)
    target = Graph.objects.create(name="retired-switch-target", org=acme)

    result = PartialImportService(entity_registry).import_data(
        data, target, org_id=acme.id, user=admin_acme
    )

    [python_node] = result.content["python_node_list"]
    [webhook_node] = result.content["webhook_trigger_node_list"]
    assert tuple(python_node[box] for box in BOXES) == expected
    assert tuple(webhook_node[box] for box in BOXES) == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("switch", "expected"),
    [(False, (False,) * 3), (True, (True,) * 3), (None, (True,) * 3)],
)
def test_partial_import_of_a_classification_decision_table(
    acme, admin_acme, source_graph, switch, expected
):
    data = _partial_export(
        source_graph,
        acme,
        EntityType.CLASSIFICATION_DECISION_TABLE_NODE,
        [source_graph.classification_decision_table_node_list.get().id],
    )
    _write_old_switches(data, pre_switch=switch, post_switch=switch)
    target = Graph.objects.create(name="retired-switch-cdt-target", org=acme)

    result = PartialImportService(entity_registry).import_data(
        data, target, org_id=acme.id, user=admin_acme
    )

    [imported] = result.content["classification_decision_table_node_list"]
    for prefix in ("pre_", "post_"):
        assert tuple(imported[f"{prefix}{box}"] for box in BOXES) == expected
