"""Import refuses a flow holding a template or state path crew would refuse, synchronously and
as a job; partial import does not."""

import os

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.import_export.export_format_strategies import ArchiveExportFormatStrategy
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.schemas import ImportSettings
from tables.models import Graph, TransferJob
from tables.models.graph_models import (
    AgentNode,
    AgentNodeTask,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    TaskNode,
)
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tables.services.transfer_jobs.job_service import TransferJobService
from tables.services.transfer_jobs.runner import IMPORT_ARCHIVE_NAME, TransferJobRunner
from tests.helpers import UNRESTRICTED_EXPORT_POLICY, data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_backend_fake import FakeStorageBackend
from tables.import_export.utils import flatten_error_detail

REFUSED_UNDERSCORE_KEY = (
    "Placeholder '{a._b}' is not allowed: '_b' starts with '_'. Rename that variable or key."
)
REFUSED_CONVERSION = (
    "Placeholder '{topic!r}' is not allowed: conversions such as '!r' are not supported. "
    "Write '{topic}'."
)


def _task_with_refused_instructions(graph):
    TaskNode.objects.create(graph=graph, node_name="Writer", instructions="Use {a._b}")
    return f"Node 'Writer' of flow 'Source', field 'instructions': {REFUSED_UNDERSCORE_KEY}"


def _agent_task_with_refused_instructions(graph):
    agent = AgentNode.objects.create(graph=graph, node_name="Helper")
    AgentNodeTask.objects.create(agent_node=agent, name="only", order=0, instructions="{topic!r}")
    return f"Node 'Helper' of flow 'Source', field 'tasks[0].instructions': {REFUSED_CONVERSION}"


def _classification_prompt_with_refused_text(graph):
    classifier = ClassificationDecisionTableNode.objects.create(graph=graph, node_name="Classifier")
    ClassificationDecisionTablePrompt.objects.create(
        cdt_node=classifier, prompt_key="rate", prompt_text="Rate {a._b}"
    )
    return (
        "Node 'Classifier' of flow 'Source', field 'prompt_configs[0].prompt_text': "
        f"{REFUSED_UNDERSCORE_KEY}"
    )


def _classification_input_map_with_refused_path(graph):
    ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="Classifier", pre_input_map={"x": "variables._x|null"}
    )
    return (
        "Node 'Classifier' of flow 'Source', field 'pre_input_map': Variable path "
        "'variables._x' is not allowed: path segments cannot start with '_'."
    )


def _task_with_refused_output_path(graph):
    TaskNode.objects.create(graph=graph, node_name="Writer", output_variable_path="variables._out")
    return (
        "Node 'Writer' of flow 'Source', field 'output_variable_path': Variable path "
        "'variables._out' is not allowed: path segments cannot start with '_'."
    )


def _export(graph):
    return ExportService(entity_registry).export_entities(
        EntityType.GRAPH, [graph.id], policy=UNRESTRICTED_EXPORT_POLICY
    )


def _export_file(graph):
    return data_to_json_file(data=_export(graph).data, filename="flow.json")


@pytest.fixture
def export_archive_path(source):
    """The path of `source` exported as an archive, taken once a test has seeded its nodes."""
    paths = []

    def _write():
        paths.append(ArchiveExportFormatStrategy().render_to_file(_export(source)))
        return paths[-1]

    yield _write
    for path in paths:
        os.unlink(path)


@pytest.fixture
def backend():
    return FakeStorageBackend()


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def source(acme):
    return Graph.objects.create(name="Source", org=acme)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "seed_refused_node",
    [
        pytest.param(_task_with_refused_instructions, id="task-instructions"),
        pytest.param(_agent_task_with_refused_instructions, id="agent-task-instructions"),
        pytest.param(_classification_prompt_with_refused_text, id="classification-prompt"),
        pytest.param(
            _classification_input_map_with_refused_path, id="classification-table-input-map"
        ),
        pytest.param(_task_with_refused_output_path, id="state-path"),
    ],
)
def test_an_import_with_a_run_refusal_is_a_400_and_creates_no_flow(
    acme_client, source, seed_refused_node
):
    # Saved before this check existed, then exported.
    expected_message = seed_refused_node(source)
    file = _export_file(source)
    graph_count_before = Graph.objects.count()

    response = acme_client.post(reverse("graphs-import-entity"), {"file": file}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"][0]["detail"] == expected_message
    assert Graph.objects.count() == graph_count_before


@pytest.mark.django_db
def test_an_import_job_with_a_run_refusal_is_refused_before_anything_is_stored(
    admin_acme, acme, source, export_archive_path, backend
):
    expected_message = _task_with_refused_instructions(source)

    with pytest.raises(ValidationError) as refused:
        TransferJobService().start_import(
            user=admin_acme,
            org_id=acme.id,
            entity_type=EntityType.GRAPH,
            settings=ImportSettings(),
            archive_path=export_archive_path(),
            store=TransferArchiveStore(backend=backend),
        )

    # The upload route answers 400 with this message, as the synchronous import does.
    assert flatten_error_detail(refused.value.detail) == expected_message
    assert not TransferJob.objects.exists()
    assert backend.objects == {}


@pytest.mark.django_db
def test_an_import_job_whose_stored_archive_holds_a_run_refusal_fails_with_the_refusal(
    admin_acme, acme, source, export_archive_path, backend
):
    expected_message = _task_with_refused_instructions(source)
    store = TransferArchiveStore(backend=backend)
    job = TransferJob.objects.create(
        org=acme,
        created_by=admin_acme,
        kind=TransferJob.Kind.IMPORT,
        main_entity=TransferJob.MainEntity.FLOW,
        request={"settings": {}},
    )
    with open(export_archive_path(), "rb") as archive:
        job.archive_key = store.upload_file(job.id, IMPORT_ARCHIVE_NAME, archive)
    job.save(update_fields=["archive_key"])
    graph_count_before = Graph.objects.count()

    TransferJobRunner(store=store).run(job.id)

    job.refresh_from_db()
    assert job.status == TransferJob.Status.FAILED
    assert job.error == {"code": "invalid_file", "message": expected_message}
    assert Graph.objects.count() == graph_count_before


@pytest.mark.django_db
def test_an_import_with_data_paths_crew_runs_creates_the_flow(acme_client, source):
    TaskNode.objects.create(
        graph=source,
        node_name="Writer",
        instructions="Answer {context[user_input]} for {_private}",
        input_map={"context": "variables.context|none", "_private": "variables.private"},
        output_variable_path="variables.answer",
    )
    file = _export_file(source)

    response = acme_client.post(reverse("graphs-import-entity"), {"file": file}, format="multipart")

    assert response.status_code == status.HTTP_200_OK, response.content
    imported = TaskNode.objects.exclude(graph=source).get(node_name="Writer")
    assert imported.instructions == "Answer {context[user_input]} for {_private}"


@pytest.mark.django_db
def test_an_import_with_a_system_one_prompt_text_crew_never_renders_creates_the_flow(
    acme_client, source
):
    classifier = ClassificationDecisionTableNode.objects.create(graph=source, node_name="Classifier")
    ClassificationDecisionTablePrompt.objects.create(
        cdt_node=classifier,
        prompt_key="fast",
        kind=ClassificationDecisionTablePrompt.Kind.SYSTEM_ONE,
        prompt_text="{x!r}",
    )
    file = _export_file(source)

    response = acme_client.post(reverse("graphs-import-entity"), {"file": file}, format="multipart")

    assert response.status_code == status.HTTP_200_OK, response.content
    imported = ClassificationDecisionTablePrompt.objects.exclude(cdt_node__graph=source).get()
    assert (imported.kind, imported.prompt_text) == ("system_one", "{x!r}")


@pytest.mark.django_db
def test_a_partial_import_with_a_refused_placeholder_is_returned_unsaved(
    acme_client, acme, source
):
    # Not refused here: the pasted node lands unsaved on the canvas, and the next bulk save
    # refuses it on the exact field.
    node = TaskNode.objects.create(graph=source, node_name="Writer", instructions="Use {a._b}")
    export_data = (
        GraphPartialExportService(entity_registry)
        .export(
            [NodeRef(entity_type=EntityType.TASK_NODE, node_id=node.id)],
            org_id=acme.id,
            policy=UNRESTRICTED_EXPORT_POLICY,
        )
        .data
    )
    target = Graph.objects.create(name="Target", org=acme)

    response = acme_client.post(
        reverse("graphs-partial-import", args=[target.id]),
        {"file": data_to_json_file(data=export_data, filename="nodes.json")},
        format="multipart",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    [pasted] = response.data["content"]["task_node_list"]
    assert pasted["instructions"] == "Use {a._b}"
    assert not TaskNode.objects.filter(graph=target).exists()
