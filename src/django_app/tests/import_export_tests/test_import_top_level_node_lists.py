"""A full import refuses node lists outside a flow: inspect only reviews nodes nested in
`Flow[].nodes`, so a top-level node would be created with code nobody reviewed."""

import os

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError

from tables.import_export.constants import IMPORT_VERSION, NODE_ENTITY_TYPES
from tables.import_export.enums import EntityType
from tables.import_export.export_format_strategies import ArchiveExportFormatStrategy
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.export_service import ExportResult
from tables.import_export.services.import_service import ImportService
from tables.models import Graph, PythonCode, PythonNode, StartNode, TransferJob
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tables.services.transfer_jobs.job_service import TransferJobService
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_backend_fake import FakeStorageBackend
from utils.exception_handler import flatten_error_detail

PYTHON_NODE_REFUSAL = (
    "Node lists outside a flow are not part of an export file: PythonNode. No changes were made."
)


def _file_with(**top_level_lists) -> dict:
    return {
        "Flow": [{"id": 1, "name": "f", "metadata": {}, "nodes": []}],
        **top_level_lists,
        "main_entity": EntityType.GRAPH,
        "version": IMPORT_VERSION,
    }


def _python_node_entry() -> dict:
    return {
        "id": 5,
        "graph": 1,
        "node_name": "Hidden",
        "python_code": {"code": "def main(): return {}", "entrypoint": "main"},
    }


def _row_counts() -> tuple[int, int, int, int]:
    return (
        Graph.objects.count(),
        PythonNode.objects.count(),
        PythonCode.objects.count(),
        StartNode.objects.count(),
    )


def _import(data: dict, org) -> None:
    ImportService(entity_registry).import_data(data, EntityType.GRAPH, org_id=org.id)


@pytest.mark.django_db
def test_a_top_level_python_node_list_is_refused_and_nothing_is_written(acme):
    counts_before = _row_counts()

    with pytest.raises(ValidationError) as refused:
        _import(_file_with(PythonNode=[_python_node_entry()]), acme)

    assert flatten_error_detail(refused.value.detail) == PYTHON_NODE_REFUSAL
    assert _row_counts() == counts_before


@pytest.mark.django_db
def test_every_offending_node_list_is_named_sorted_start_node_included(acme):
    counts_before = _row_counts()

    with pytest.raises(ValidationError) as refused:
        _import(
            _file_with(
                StartNode=[{"id": 6, "graph": 1, "variables": {}}],
                PythonNode=[_python_node_entry()],
            ),
            acme,
        )

    assert flatten_error_detail(refused.value.detail) == (
        "Node lists outside a flow are not part of an export file: PythonNode, StartNode. "
        "No changes were made."
    )
    assert _row_counts() == counts_before


@pytest.mark.django_db
def test_an_empty_top_level_node_list_is_not_refused(acme):
    graph_count_before = Graph.objects.count()

    _import(_file_with(PythonNode=[]), acme)

    assert Graph.objects.count() == graph_count_before + 1


@pytest.mark.django_db
def test_the_flow_import_endpoint_answers_400_for_a_top_level_node_list(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    counts_before = _row_counts()

    response = client.post(
        reverse("graphs-import-entity"),
        {
            "file": data_to_json_file(
                data=_file_with(PythonNode=[_python_node_entry()]), filename="flow.json"
            )
        },
        format="multipart",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["message"] == PYTHON_NODE_REFUSAL
    assert _row_counts() == counts_before


@pytest.mark.django_db
def test_an_import_job_with_a_top_level_node_list_is_refused_before_anything_is_stored(
    admin_acme, acme
):
    backend = FakeStorageBackend()
    archive_path = ArchiveExportFormatStrategy().render_to_file(
        ExportResult(data=_file_with(PythonNode=[_python_node_entry()]))
    )
    try:
        with pytest.raises(ValidationError) as refused:
            TransferJobService().start_import(
                user=admin_acme,
                org_id=acme.id,
                entity_type=EntityType.GRAPH,
                settings=ImportSettings(),
                archive_path=archive_path,
                store=TransferArchiveStore(backend=backend),
            )
    finally:
        os.unlink(archive_path)

    assert flatten_error_detail(refused.value.detail) == PYTHON_NODE_REFUSAL
    assert not TransferJob.objects.exists()
    assert backend.objects == {}


def test_every_registered_node_strategy_is_refused_at_top_level():
    node_strategy_types = {
        entity_type
        for entity_type in EntityType
        if entity_registry.has_strategy(entity_type)
        and type(entity_registry.get_strategy(entity_type)).__module__.startswith(
            "tables.import_export.strategies.nodes."
        )
    }

    assert node_strategy_types
    assert node_strategy_types <= NODE_ENTITY_TYPES
