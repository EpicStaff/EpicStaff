"""An imported venv the sandbox refuses, and what an import hands the sandbox.

What a library may be is the sandbox's rule, so the gateway passes libraries on as
the file writes them and the sandbox's refusal is what fails the import. The
sandbox is the only thing replaced: the `sandbox` fixture stands in for it and
records what it was asked to create and remove.
"""

import io
import json
import os

import pytest
from proxies.sandbox.models import SandboxVenvBinding

from tables.import_export.enums import EntityType
from tables.import_export.export_format_strategies import ArchiveExportFormatStrategy
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import Graph, PythonCode, PythonCodeTool, PythonNode, TransferJob
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tables.services.transfer_jobs.runner import IMPORT_ARCHIVE_NAME, TransferJobRunner
from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.import_export_tests.venv_fakes import upstream_venv
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_backend_fake import FakeStorageBackend

pytestmark = pytest.mark.django_db

IMPORT_URL = "/api/python-code-tool/import/"
REFUSAL = "Library name \"numpy; os_name=='nt'\" is not a package name."
# The sandbox's words for a name older releases exported with its version in it.
BOUND_IN_NAME_REFUSAL = (
    "Library name 'numpy>=1' is not a package name. Use letters, digits and '.', '_' or "
    "'-' between them, optionally followed by extras in brackets, for example 'requests' "
    "or 'requests[socks,security]'; put a version in the specification."
)


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return api_client


def exported_tool(org, binding) -> dict:
    """The export file of a tool running in `binding`, made in `org`."""
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main", venv=binding)
    tool = PythonCodeTool.objects.create(
        org=org, name="Fetch orders", description="d", python_code=python_code
    )
    return (
        ExportService(entity_registry)
        .export_entities(
            EntityType.PYTHON_CODE_TOOL, [tool.id], org_id=org.id, policy=UNRESTRICTED_EXPORT_POLICY
        )
        .data
    )


def upload(export_data: dict) -> io.BytesIO:
    file = io.BytesIO(json.dumps(export_data).encode())
    file.name = "tool.json"
    return file


class TestSynchronousImport:
    @pytest.mark.parametrize(
        ("library", "refusal"),
        [
            pytest.param({"name": "numpy; os_name=='nt'"}, REFUSAL, id="marker"),
            # An export file of an earlier release, which let the version into the name.
            pytest.param(
                {"name": "numpy>=1", "specification": ""}, BOUND_IN_NAME_REFUSAL, id="bound-in-name"
            ),
        ],
    )
    def test_a_venv_the_sandbox_refuses_fails_the_import_with_its_message(
        self, client, acme, beta, sandbox, library, refusal
    ):
        """Exported from another org, so nothing in the importing org is reused and
        the tool's venv is created upstream before the refused one is reached."""
        export_data = exported_tool(beta, upstream_venv(sandbox, beta, venv_id=4711))
        export_data[EntityType.VENV].append({"id": 987654, "name": "broken-venv", "libs": [library]})
        sandbox.refusals["broken-venv"] = refusal

        response = client.post(IMPORT_URL, {"file": upload(export_data)}, format="multipart")

        assert response.status_code == 400
        assert [item["detail"] for item in response.data["errors"]] == [refusal]
        # The venv created before the refusal is compensated upstream, its binding
        # rolled back with the import.
        [removed_id] = sandbox.removed
        assert sandbox.venvs[int(removed_id)]["name"] == "scraper-venv"
        assert not SandboxVenvBinding.objects.filter(org_id=acme.id).exists()
        assert not PythonCodeTool.objects.filter(org=acme).exists()

    @pytest.mark.parametrize(
        ("name", "refusal"),
        [
            pytest.param(
                "Tool #2-venv",
                "String should match pattern '^[A-Za-z0-9 _-]+$'",
                id="refused-character",
            ),
            pytest.param("x" * 256, "String should have at most 255 characters", id="too-long"),
        ],
    )
    def test_a_venv_name_the_sandbox_refuses_fails_the_import_with_its_message(
        self, client, acme, beta, sandbox, name, refusal
    ):
        """The gateway does not judge the name: it reaches the sandbox, whose refusal
        is what the user reads."""
        export_data = exported_tool(beta, upstream_venv(sandbox, beta, venv_id=4711))
        export_data[EntityType.VENV].append({"id": 987654, "name": name, "libs": []})
        sandbox.refusals[name] = refusal

        response = client.post(IMPORT_URL, {"file": upload(export_data)}, format="multipart")

        assert response.status_code == 400
        assert [item["detail"] for item in response.data["errors"]] == [refusal]
        assert not SandboxVenvBinding.objects.filter(org_id=acme.id).exists()
        assert not PythonCodeTool.objects.filter(org=acme).exists()

    def test_libraries_reach_the_sandbox_exactly_as_the_file_writes_them(
        self, client, acme, beta, sandbox
    ):
        libs = [
            {"name": "numpy>=1", "specification": ""},
            {"name": "pydantic", "specification": ">=1.0, <2"},
            {"name": "requests[socks]>=2", "specification": ""},
            # Not trimmed and not refused: whether that is a library is the sandbox's call.
            {"name": " httpx ", "specification": " >=0.27 "},
            {"name": "", "specification": ""},
        ]
        export_data = exported_tool(beta, upstream_venv(sandbox, beta, venv_id=4711, libs=libs))

        response = client.post(IMPORT_URL, {"file": upload(export_data)}, format="multipart")

        assert response.status_code == 200, response.data
        binding = SandboxVenvBinding.objects.get(org_id=acme.id)
        assert sandbox.venvs[int(binding.resource_id)]["libs"] == libs


class TestImportJob:
    """The background import: the refusal is the job's error, not a generic failure."""

    def test_a_venv_the_sandbox_refuses_fails_the_job_with_its_message(
        self, default_org, regular_user, sandbox
    ):
        # Failed builds are never reused, so the import creates both venvs anew.
        graph = Graph.objects.create(name="Flow", metadata={"nodes": [], "edges": []}, org=default_org)
        for venv_id, name in [(4711, "scraper-venv"), (4712, "broken-venv")]:
            binding = upstream_venv(sandbox, default_org, venv_id=venv_id, name=name, status="failed")
            python_code = PythonCode.objects.create(
                code="def main(): return 1", entrypoint="main", venv=binding
            )
            PythonNode.objects.create(graph=graph, python_code=python_code, node_name=name)
        archive = ArchiveExportFormatStrategy().render_to_file(
            ExportService(entity_registry).export_entities(
                EntityType.GRAPH, [graph.id], policy=UNRESTRICTED_EXPORT_POLICY
            )
        )
        # The org already has a venv of that name, so the import creates it renamed.
        sandbox.refusals["broken-venv-2"] = REFUSAL
        store = TransferArchiveStore(backend=FakeStorageBackend())
        job = TransferJob.objects.create(
            org=default_org,
            created_by=regular_user,
            kind=TransferJob.Kind.IMPORT,
            main_entity=TransferJob.MainEntity.FLOW,
            request={"settings": {}},
        )
        try:
            with open(archive, "rb") as file:
                job.archive_key = store.upload_file(job.id, IMPORT_ARCHIVE_NAME, file)
        finally:
            os.unlink(archive)
        job.save(update_fields=["archive_key"])
        bindings_before = set(SandboxVenvBinding.objects.values_list("pk", flat=True))

        TransferJobRunner(store=store).run(job.id)

        job.refresh_from_db()
        assert job.status == TransferJob.Status.FAILED
        assert job.error == {"code": "invalid_file", "message": REFUSAL}
        # The flow's venvs are imported in no fixed order, so `scraper-venv-2` is created
        # before the refusal or not at all; whatever the job created upstream is removed.
        created_by_job = {venv_id for venv_id in sandbox.venvs if venv_id not in (4711, 4712)}
        assert {int(removed_id) for removed_id in sandbox.removed} == created_by_job
        assert [sandbox.venvs[venv_id]["name"] for venv_id in created_by_job] in (
            [],
            ["scraper-venv-2"],
        )
        assert set(SandboxVenvBinding.objects.values_list("pk", flat=True)) == bindings_before
