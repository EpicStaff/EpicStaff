"""Synchronous imports take the `.zip` an export job produced as well as an older `.json`.

Only an import job reads a knowledge collection's files out of an archive, so a `.zip`
carrying collections sent to a synchronous import is refused with `use_import_job`.
"""

import io
import json
import zipfile

import pytest

from tables.import_export.archive import ENVELOPE_MEMBER
from tables.import_export.constants import IMPORT_VERSION, MAIN_ENTITY_KEY
from tables.import_export.enums import EntityType
from tables.models import (
    ClassificationDecisionTableNode,
    Graph,
    PythonCode,
    PythonCodeTool,
    PythonNode,
)
from tables.services.transfer_jobs import job_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.transfer_job_helpers import export_via_job

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_queue(monkeypatch):
    monkeypatch.setattr(job_service, "enqueue_transfer_job", lambda job: None)


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return api_client


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Source flow", metadata={"nodes": [], "edges": []}, org=acme)


@pytest.fixture
def target_flow(acme):
    return Graph.objects.create(name="Target flow", metadata={"nodes": [], "edges": []}, org=acme)


def _upload(data: bytes, name: str) -> io.BytesIO:
    file = io.BytesIO(data)
    file.name = name
    return file


def _zip(envelope: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(ENVELOPE_MEMBER, json.dumps(envelope))
    return buffer.getvalue()


def _flow_envelope_with_a_collection() -> dict:
    return {
        MAIN_ENTITY_KEY: EntityType.GRAPH,
        "version": IMPORT_VERSION,
        EntityType.GRAPH: [],
        EntityType.SOURCE_COLLECTION: [{"collection_id": 1, "collection_name": "Handbook"}],
    }


def _collection_envelope() -> dict:
    return {
        MAIN_ENTITY_KEY: EntityType.SOURCE_COLLECTION,
        "version": IMPORT_VERSION,
        EntityType.SOURCE_COLLECTION: [{"collection_id": 1, "collection_name": "Handbook"}],
    }


def _python_node(flow) -> PythonNode:
    return PythonNode.objects.create(
        graph=flow, python_code=PythonCode.objects.create(code="# pasted"), node_name="py"
    )


# --- importing whole items -------------------------------------------------------------------


@pytest.mark.parametrize("file_kind", ["zip", "json"])
def test_a_flow_export_imports_synchronously_from_a_zip_or_its_json(client, acme, flow, file_kind):
    exported = export_via_job(
        client, "/api/graphs/export-jobs/", {"ids": [flow.id], "include_knowledge": False}
    )
    upload = (
        exported.upload("flow.zip")
        if file_kind == "zip"
        else _upload(exported.members[ENVELOPE_MEMBER], "flow.json")
    )

    response = client.post("/api/graphs/import/", {"file": upload}, format="multipart")

    assert response.status_code == 200, response.content
    assert Graph.objects.filter(org=acme, name__startswith="Source flow").count() == 2


def test_a_flow_zip_carrying_collections_is_sent_to_the_flow_import_job(client, acme):
    graphs_before = Graph.objects.count()

    response = client.post(
        "/api/graphs/import/",
        {"file": _upload(_zip(_flow_envelope_with_a_collection()), "flow.zip")},
        format="multipart",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "use_import_job"
    assert "flow import job" in response.json()["message"]
    assert Graph.objects.count() == graphs_before


@pytest.mark.parametrize(
    ("url", "envelope"),
    [
        pytest.param(
            "/api/python-code-tool/import/", _flow_envelope_with_a_collection(), id="flow to tools"
        ),
        pytest.param("/api/mcp-tools/import/", _collection_envelope(), id="collection to mcp"),
        pytest.param("/api/graphs/import/", _collection_envelope(), id="collection to flows"),
    ],
)
def test_a_zip_of_another_entity_carrying_collections_is_the_wrong_entity(client, url, envelope):
    response = client.post(
        url, {"file": _upload(_zip(envelope), "export.zip")}, format="multipart"
    )

    assert response.status_code == 400
    assert response.json()["code"] != "use_import_job"
    assert "Provided wrong entity" in str(response.json())


@pytest.mark.parametrize(
    ("over_the_cap", "status"),
    [pytest.param(False, 200, id="at the cap"), pytest.param(True, 400, id="one byte over")],
)
def test_a_sync_import_zip_is_capped_in_size(client, acme, settings, over_the_cap, status):
    tool = PythonCodeTool.objects.create(
        name="Lookup",
        description="Looks a value up.",
        python_code=PythonCode.objects.create(code="def main(): return 1", entrypoint="main"),
        org=acme,
    )
    exported = export_via_job(client, "/api/python-code-tool/export-jobs/", {"ids": [tool.id]})
    settings.MAX_KNOWLEDGE_ARCHIVE_SIZE = len(exported.archive) - (1 if over_the_cap else 0)

    response = client.post(
        "/api/python-code-tool/import/", {"file": exported.upload("tool.zip")}, format="multipart"
    )

    assert response.status_code == status, response.content
    assert PythonCodeTool.objects.filter(org=acme).count() == (1 if over_the_cap else 2)


@pytest.mark.parametrize(
    ("content", "name"),
    [
        pytest.param(b"not json {{{", "broken.json", id="broken json"),
        pytest.param(b"PK\x03\x04 not really a zip", "broken.zip", id="broken zip"),
    ],
)
def test_an_unreadable_upload_is_refused(client, content, name):
    response = client.post(
        "/api/python-code-tool/import/", {"file": _upload(content, name)}, format="multipart"
    )

    assert response.status_code == 400


# --- partial import into a flow ----------------------------------------------------------


def test_nodes_exported_as_a_job_paste_into_another_flow(client, flow, target_flow):
    node = _python_node(flow)
    exported = export_via_job(
        client, f"/api/graphs/{flow.id}/partial-export-jobs/", {"python_node_list": [node.id]}
    )

    response = client.post(
        f"/api/graphs/{target_flow.id}/partial-import/",
        {"file": exported.upload("nodes.zip")},
        format="multipart",
    )

    assert response.status_code == 200, response.content
    pasted = response.json()["content"]["python_node_list"]
    assert [pasted_node["python_code"]["code"] for pasted_node in pasted] == ["# pasted"]


def test_an_older_partial_export_json_still_pastes(client, flow, target_flow):
    node = _python_node(flow)
    exported = export_via_job(
        client, f"/api/graphs/{flow.id}/partial-export-jobs/", {"python_node_list": [node.id]}
    )

    response = client.post(
        f"/api/graphs/{target_flow.id}/partial-import/",
        {"file": _upload(exported.members[ENVELOPE_MEMBER], "nodes.json")},
        format="multipart",
    )

    assert response.status_code == 200, response.content
    assert len(response.json()["content"]["python_node_list"]) == 1


def test_a_decision_table_json_export_pastes_into_a_flow(client, flow, target_flow):
    node = ClassificationDecisionTableNode.objects.create(graph=flow, node_name="Router")
    exported = export_via_job(
        client,
        "/api/classification-decision-table-node/export-jobs/",
        {"ids": [node.id], "export_format": "json"},
    )

    response = client.post(
        f"/api/graphs/{target_flow.id}/partial-import/",
        {"file": exported.upload("router.zip")},
        format="multipart",
    )

    assert response.status_code == 200, response.content
    pasted = response.json()["content"]["classification_decision_table_node_list"]
    assert [pasted_node["node_name"] for pasted_node in pasted] == ["Router"]


@pytest.mark.parametrize(
    ("content", "code"),
    [
        pytest.param(_zip(_flow_envelope_with_a_collection()), "use_import_job", id="flow"),
        pytest.param(_zip(_collection_envelope()), "use_import_job", id="collection"),
        pytest.param(b"[1, 2]", "invalid", id="not an object"),
        pytest.param(b"not json", "invalid", id="broken json"),
    ],
)
def test_a_partial_import_refuses_what_it_cannot_paste(client, target_flow, content, code):
    response = client.post(
        f"/api/graphs/{target_flow.id}/partial-import/",
        {"file": _upload(content, "nodes")},
        format="multipart",
    )

    assert response.status_code == 400
    assert response.json()["code"] == code


@pytest.mark.parametrize(
    ("envelope", "job"),
    [
        pytest.param(_flow_envelope_with_a_collection(), "a flow import job", id="flow"),
        pytest.param(_collection_envelope(), "a knowledge collection import job", id="collection"),
    ],
)
def test_use_import_job_names_the_job_that_takes_the_zip(client, target_flow, envelope, job):
    response = client.post(
        f"/api/graphs/{target_flow.id}/partial-import/",
        {"file": _upload(_zip(envelope), "nodes.zip")},
        format="multipart",
    )

    assert response.status_code == 400
    assert response.json()["message"] == (
        f"This archive carries knowledge collections; import it as {job}."
    )
