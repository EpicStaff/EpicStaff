"""Sequential (non-concurrent) service-layer tests for
OrganizationManagementService.deactivate_organization.

These tests cover the four distinct branch paths through the method that are
not exercised by the concurrency suite in
test_organization_management_service_concurrency.py:

  1. Active org deactivated successfully when others remain.
  2. Last active org raises LastActiveOrganizationError.
  3. Already-inactive org is a silent no-op (does not raise even when it is the
     only inactive org and the active set has exactly one member).
  4. Nonexistent org_id raises OrganizationNotFoundError.

Plain @pytest.mark.django_db is sufficient -- no cross-connection visibility
or FOR UPDATE serialization is under test here.

What is NOT duplicated here:
  - Concurrent deactivation race (two threads, last two active orgs) --
    covered in test_organization_management_service_concurrency.py.
  - Both-succeed case with three active orgs under concurrency -- same file.
"""

import pytest

from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from rbac.governance.organizations import (
    OrganizationManagementService,
)
from rbac.exceptions import (
    DefaultOrganizationNotDeletableError,
    LastActiveOrganizationError,
    LastOrganizationError,
    OrganizationNotFoundError,
)


@pytest.fixture
def service():
    return OrganizationManagementService()


@pytest.mark.django_db
def test_deactivate_active_org_succeeds_when_others_remain(service):
    """Deactivating one of two active organizations succeeds.

    The if-branch fires (org_id in orgs_map) and len(orgs_map) == 2 > 1, so
    the guard allows the deactivation. The returned org has is_active=False
    and the sibling org remains active.
    """
    Organization.objects.filter(is_active=True).update(is_active=False)

    org_a = Organization.objects.create(name="SeqDeactivateA", is_active=True)
    org_b = Organization.objects.create(name="SeqDeactivateB", is_active=True)

    result = service.deactivate_organization(org_a.pk)

    assert result.pk == org_a.pk
    assert result.is_active is False

    org_a.refresh_from_db()
    assert org_a.is_active is False

    org_b.refresh_from_db()
    assert org_b.is_active is True


@pytest.mark.django_db
def test_deactivate_last_active_org_raises(service):
    """Deactivating the sole active organization raises LastActiveOrganizationError.

    The if-branch fires (org_id in orgs_map) and len(orgs_map) == 1, which
    trips the guard immediately.
    """
    Organization.objects.filter(is_active=True).update(is_active=False)

    org = Organization.objects.create(name="SeqLastActive", is_active=True)

    with pytest.raises(LastActiveOrganizationError):
        service.deactivate_organization(org.pk)

    org.refresh_from_db()
    assert org.is_active is True


@pytest.mark.django_db
def test_deactivate_already_inactive_org_is_no_op(service):
    """Deactivating an already-inactive org is a silent no-op.

    The else-branch fires (_get_locked_org) because the target is not in
    orgs_map (inactive orgs are excluded from the active-set query). The
    subsequent `if target.is_active` guard is False, so the save is skipped.
    No LastActiveOrganizationError is raised even though the system has exactly
    one active org -- B is already inactive, so the invariant is not threatened.
    """
    Organization.objects.filter(is_active=True).update(is_active=False)

    Organization.objects.create(name="SeqIdempotentGuard", is_active=True)
    org_b = Organization.objects.create(name="SeqIdempotentTarget", is_active=False)

    result = service.deactivate_organization(org_b.pk)

    assert result.pk == org_b.pk
    assert result.is_active is False

    org_b.refresh_from_db()
    assert org_b.is_active is False


@pytest.mark.django_db
def test_deactivate_nonexistent_org_raises_not_found(service):
    """Deactivating an org_id that matches no row raises OrganizationNotFoundError.

    The else-branch fires (_get_locked_org) and translates DoesNotExist into
    the project-standard 404 envelope.
    """
    with pytest.raises(OrganizationNotFoundError):
        service.deactivate_organization(999_999)


# ---------------------------------------------------------------------------
# delete_organization
#
# build_affected_resources unit tests live in test_delete_collector.py --
# it's shared with UserManagementService, not specific to this service.
# ---------------------------------------------------------------------------


def test_default_organization_not_deletable_error_shape():
    error = DefaultOrganizationNotDeletableError()
    assert error.status_code == 400
    assert error.default_code == "default_organization_not_deletable"


def test_last_organization_error_shape():
    error = LastOrganizationError()
    assert error.status_code == 400
    assert error.default_code == "last_organization"


@pytest.fixture
def actor(db, django_user_model):
    user = django_user_model.objects.create_user(
        email="org-delete-actor@x.com", password="StrongPass123!"
    )
    user.is_superadmin = True
    user.save(update_fields=["is_superadmin"])
    return user


@pytest.fixture
def populated_org(db):
    from tables.models.graph_models import Graph
    from tables.models.label_models import Label

    org = Organization.objects.create(name="Doomed Org")
    Graph.objects.create(name="doomed-graph", org=org)
    Label.objects.create(name="doomed-label", org=org)
    return org


@pytest.fixture
def _surviving_org(db):
    """A second org so `populated_org` is never the last one."""
    return Organization.objects.create(name="Survivor Org")


@pytest.fixture(autouse=True)
def _no_storage_calls(mocker):
    """Storage is a network dependency; stub it for every service test in this file."""
    backend = mocker.MagicMock()
    backend.list_all_objects.return_value = [("a.txt", 10, ""), ("b.txt", 5, "")]
    return mocker.patch(
        "tables.services.rbac.organization_management_service.get_storage_backend",
        return_value=backend,
    )


def _grouped_row_counts() -> dict[str, int]:
    """Count every installed model's rows through its base manager (so soft-delete filters cannot hide a row), folded under the same friendly resource name `affected_resources` reports under."""
    from django.apps import apps

    from tables.services.rbac.delete_resource_names import resource_name

    counts: dict[str, int] = {}
    for model in apps.get_models():
        name = resource_name(model._meta.label)
        if name is None:
            continue
        counts[name] = counts.get(name, 0) + model._base_manager.count()
    return counts


def _assert_report_matched_reality(predicted: dict[str, int], before: dict, after: dict):
    """Assert every resource lost exactly the rows the report predicted, and no resource lost unpredicted rows."""
    for name, before_count in before.items():
        removed = before_count - after[name]
        expected = predicted.get(name, 0)
        assert removed == expected, (
            f"{name}: report predicted {expected} removed, actually removed {removed}"
        )
    assert set(predicted) <= set(before), "report named a resource that does not exist"


@pytest.mark.django_db
def test_delete_organization_unknown_id_raises_not_found(db, actor):
    with pytest.raises(OrganizationNotFoundError):
        OrganizationManagementService().preview_delete(
            actor=actor, org_id=999999
        )


@pytest.mark.django_db
def test_org_dry_run_prediction_matches_what_the_delete_actually_removes(
    actor, populated_org, _surviving_org, django_user_model, issue_api_key
):
    """The load-bearing guarantee: the delete removes exactly the rows the preview predicted, and nothing else."""
    role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    member = django_user_model.objects.create_user(
        email="cross-check-member@x.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=member, org=populated_org, role=role)
    issue_api_key(user=member, name="cross-check-member-key")
    Role.objects.create(name="Cross-check Custom Role", is_built_in=False, org=populated_org)

    service = OrganizationManagementService()
    preview = service.preview_delete(actor=actor, org_id=populated_org.pk)

    # storage_files counts MinIO objects, not a Django model row, so it has
    # no counterpart in _grouped_row_counts() and is excluded from this
    # DB-reality cross-check.
    predicted = {k: v for k, v in preview.affected_resources.items() if k != "storage_files"}
    before = _grouped_row_counts()

    service.delete_organization(actor=actor, org_id=populated_org.pk)

    _assert_report_matched_reality(predicted, before, _grouped_row_counts())


@pytest.mark.django_db
def test_delete_organization_report_passes_through_the_documented_serializer(
    actor, populated_org, _surviving_org
):
    """OrganizationDeleteReportSerializer must accept the real preview_delete output, not just a hand-written fixture."""
    import dataclasses

    from tables.serializers.delete_serializers import OrganizationDeleteReportSerializer

    report = OrganizationManagementService().preview_delete(
        actor=actor, org_id=populated_org.pk
    )

    serializer = OrganizationDeleteReportSerializer(data=dataclasses.asdict(report))
    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_org_report_is_stable_across_calls(actor, populated_org, _surviving_org):
    """Two service calls against the same org report an identical affected_resources block."""
    from tables.models.crew_models import Agent, Crew, Task
    from tables.models.knowledge_models.collection_models import SourceCollection

    # Enriched with a `SourceCollection` and a `Task` linked to the org --
    # both swept outside the Collector's own closure before the real delete's
    # cascade runs -- so this pins the merged-count invariant the sweep-report
    # fix depends on. A thinner fixture (as this test previously used) cannot
    # catch a regression where the dry-run and real reports diverge only on
    # swept rows.
    SourceCollection.objects.create(org=populated_org, collection_name="stability-check-docs")
    crew = Crew.objects.create(org=populated_org, name="stability-check-crew")
    agent = Agent.objects.create(org=populated_org, role="r", goal="g", backstory="b")
    Task.objects.create(
        crew=crew, agent=agent, name="t", instructions="i", expected_output="e"
    )

    service = OrganizationManagementService()
    preview = service.preview_delete(actor=actor, org_id=populated_org.pk)
    actual = service.delete_organization(actor=actor, org_id=populated_org.pk)
    assert preview.affected_resources == actual.affected_resources


@pytest.mark.django_db
def test_org_report_agrees_for_a_delete_touching_the_rag_family(
    actor, populated_org, _surviving_org
):
    """A preview and the real delete report identical affected_resources when the org owns a NaiveRag under a SourceCollection (RAG-family rows are excluded sub-detail, folded into "knowledge_collections")."""
    from tables.models.knowledge_models.collection_models import BaseRagType, SourceCollection
    from tables.models.knowledge_models.naive_rag_models import NaiveRag

    collection = SourceCollection.objects.create(
        org=populated_org, collection_name="rag-divergence-check-docs"
    )
    base_rag_type = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
    )
    NaiveRag.objects.create(base_rag_type=base_rag_type)

    service = OrganizationManagementService()
    preview = service.preview_delete(actor=actor, org_id=populated_org.pk)
    actual = service.delete_organization(actor=actor, org_id=populated_org.pk)
    assert preview.affected_resources == actual.affected_resources


@pytest.mark.django_db
def test_org_delete_removes_owned_rows(actor, populated_org, _surviving_org):
    from tables.models.graph_models import Graph
    from tables.models.label_models import Label

    OrganizationManagementService().delete_organization(
        actor=actor, org_id=populated_org.pk
    )
    assert not Organization.objects.filter(pk=populated_org.pk).exists()
    assert not Graph.all_objects.filter(org_id=populated_org.pk).exists()
    # Label has no soft-delete capability, so _base_manager is identical to
    # .objects here -- unlike the Graph.all_objects check above, this isn't
    # closing a real soft-delete blind spot, just matching the file's
    # _base_manager convention for consistency.
    assert not Label._base_manager.filter(org_id=populated_org.pk).exists()


@pytest.mark.django_db
def test_org_delete_leaves_other_orgs_untouched(actor, populated_org, _surviving_org):
    from tables.models.graph_models import Graph

    keeper_graph = Graph.objects.create(name="keeper", org=_surviving_org)

    OrganizationManagementService().delete_organization(
        actor=actor, org_id=populated_org.pk
    )

    assert Organization.objects.filter(pk=_surviving_org.pk).exists()
    assert Graph.objects.filter(pk=keeper_graph.pk).exists()


@pytest.mark.django_db
def test_built_in_roles_survive_an_org_delete(actor, populated_org, _surviving_org):
    before = Role.objects.filter(is_built_in=True, org__isnull=True).count()
    OrganizationManagementService().delete_organization(
        actor=actor, org_id=populated_org.pk
    )
    assert Role.objects.filter(is_built_in=True, org__isnull=True).count() == before


@pytest.mark.django_db
def test_custom_roles_of_the_org_are_deleted(actor, populated_org, _surviving_org):
    custom = Role.objects.create(name="Custom", is_built_in=False, org=populated_org)
    OrganizationManagementService().delete_organization(
        actor=actor, org_id=populated_org.pk
    )
    assert not Role.objects.filter(pk=custom.pk).exists()


@pytest.mark.django_db
def test_org_delete_sweeps_orphaned_document_content(actor, populated_org, _surviving_org):
    """A real org delete sweeps the org's SourceCollections so their DocumentContent rows don't survive as orphans."""
    from tables.models.knowledge_models.collection_models import (
        DocumentContent,
        DocumentMetadata,
        SourceCollection,
    )

    collection = SourceCollection.objects.create(org=populated_org, collection_name="docs")
    content = DocumentContent.objects.create(content=b"hello world")
    DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=content,
        file_name="hello.txt",
    )

    OrganizationManagementService().delete_organization(
        actor=actor, org_id=populated_org.pk
    )

    assert not SourceCollection.objects.filter(pk=collection.pk).exists()
    assert not DocumentContent.objects.filter(pk=content.pk).exists()


@pytest.mark.django_db
def test_org_delete_sweeps_orphan_prone_deprecated_rows(actor, populated_org, _surviving_org):
    """A real org delete removes Task/TemplateAgent/RealtimeAgentChat rows currently linked to the org's Crew/Agent/LLMConfig/realtime configs, instead of leaving them behind with nulled FKs and unreachable prompt/config text."""
    from tables.models.crew_models import Agent, Crew, Task, TemplateAgent
    from tables.models.llm_models import LLMConfig
    from tables.models.realtime_models import OpenAIRealtimeConfig, RealtimeAgentChat

    crew = Crew.objects.create(org=populated_org, name="c")
    agent = Agent.objects.create(org=populated_org, role="r", goal="g", backstory="b")
    task = Task.objects.create(
        crew=crew, agent=agent, name="t", instructions="i", expected_output="e"
    )

    llm_config = LLMConfig.objects.create(custom_name="doomed-llm", org=populated_org)
    template_agent = TemplateAgent.objects.create(
        role="r", goal="g", backstory="b", llm_config=llm_config
    )

    openai_config = OpenAIRealtimeConfig.objects.create(
        org=populated_org, custom_name="doomed-openai"
    )
    chat = RealtimeAgentChat.objects.create(connection_key="k", openai_config=openai_config)

    OrganizationManagementService().delete_organization(
        actor=actor, org_id=populated_org.pk
    )

    assert not Task.objects.filter(pk=task.pk).exists()
    assert not TemplateAgent.objects.filter(pk=template_agent.pk).exists()
    assert not RealtimeAgentChat.objects.filter(pk=chat.pk).exists()


@pytest.mark.django_db
def test_dry_run_reports_the_sweep_as_removed_rows(actor, populated_org, _surviving_org):
    """The dry-run preview must report the swept Task/TemplateAgent/RealtimeAgentChat/SourceCollection rows as removed resources, not silently drop them -- the exact misreport the critical fix closes."""
    from tables.models.crew_models import Agent, Crew, Task
    from tables.models.knowledge_models.collection_models import SourceCollection

    SourceCollection.objects.create(org=populated_org, collection_name="preview-docs")
    crew = Crew.objects.create(org=populated_org, name="preview-crew")
    agent = Agent.objects.create(org=populated_org, role="r", goal="g", backstory="b")
    Task.objects.create(crew=crew, agent=agent, name="t", instructions="i", expected_output="e")

    preview = OrganizationManagementService().preview_delete(
        actor=actor, org_id=populated_org.pk
    )

    assert preview.affected_resources.get("tasks") == 1
    assert preview.affected_resources.get("knowledge_collections") == 1


@pytest.mark.django_db
def test_org_delete_sweeps_conversation_recordings_and_purges_their_files(
    actor, populated_org, _surviving_org, settings, tmp_path, django_capture_on_commit_callbacks
):
    """A real org delete removes ConversationRecording rows cascaded from swept RealtimeAgentChat rows and purges their audio files from storage, and the preview discloses the combined storage_files count identically in dry-run and real mode."""
    # `_no_storage_calls` (autouse) stubs the MinIO listing at 2 objects, so
    # `storage_files` is expected to be 2 (MinIO) + 1 (this recording) = 3.
    from pathlib import Path

    from django.core.files.uploadedfile import SimpleUploadedFile

    from tables.models.realtime_models import (
        ConversationRecording,
        OpenAIRealtimeConfig,
        RealtimeAgentChat,
    )

    settings.MEDIA_ROOT = str(tmp_path)
    openai_config = OpenAIRealtimeConfig.objects.create(
        org=populated_org, custom_name="doomed-openai"
    )
    chat = RealtimeAgentChat.objects.create(connection_key="k", openai_config=openai_config)
    recording = ConversationRecording.objects.create(
        rt_agent_chat=chat, recording_type=ConversationRecording.RecordingType.INBOUND
    )
    recording.file.save("clip.wav", SimpleUploadedFile("clip.wav", b"fake-audio"), save=True)
    stored = Path(settings.MEDIA_ROOT) / recording.file.name
    assert stored.exists(), "fixture failed to write the recording file"

    service = OrganizationManagementService()
    preview = service.preview_delete(actor=actor, org_id=populated_org.pk)
    assert preview.affected_resources.get("storage_files") == 3
    assert stored.exists(), "a dry run must not touch the file"

    with django_capture_on_commit_callbacks(execute=True):
        actual = service.delete_organization(actor=actor, org_id=populated_org.pk)

    assert actual.affected_resources.get("storage_files") == 3
    assert not ConversationRecording.objects.filter(pk=recording.pk).exists()
    assert not RealtimeAgentChat.objects.filter(pk=chat.pk).exists()
    assert not stored.exists()


@pytest.mark.django_db
def test_org_delete_purges_content_even_when_soft_delete_enabled(
    actor, populated_org, _surviving_org, settings
):
    """The org sweep hard-deletes SourceCollection content regardless of settings.SOFT_DELETE: a permanently-deleted org's content must not survive it under the platform's soft-delete default."""
    from tables.models.knowledge_models.collection_models import (
        DocumentContent,
        DocumentMetadata,
        SourceCollection,
    )

    settings.SOFT_DELETE = True
    collection = SourceCollection.objects.create(org=populated_org, collection_name="soft-delete-docs")
    content = DocumentContent.objects.create(content=b"hello world")
    DocumentMetadata.objects.create(
        source_collection=collection, document_content=content, file_name="hello.txt"
    )

    OrganizationManagementService().delete_organization(
        actor=actor, org_id=populated_org.pk
    )

    assert not SourceCollection.all_objects.filter(pk=collection.pk).exists()
    assert not DocumentContent.objects.filter(pk=content.pk).exists()


@pytest.mark.django_db
def test_org_delete_sweeps_already_soft_deleted_collections(actor, populated_org, _surviving_org, settings):
    """A collection soft-deleted before the org delete started is still swept: the enumeration must use SourceCollection.all_objects, not the soft-delete-filtered .objects, or its DocumentContent survives as an orphan."""
    from tables.models.knowledge_models.collection_models import (
        DocumentContent,
        DocumentMetadata,
        SourceCollection,
    )

    settings.SOFT_DELETE = True
    collection = SourceCollection.objects.create(org=populated_org, collection_name="already-gone-docs")
    content = DocumentContent.objects.create(content=b"hello world")
    DocumentMetadata.objects.create(
        source_collection=collection, document_content=content, file_name="hello.txt"
    )
    collection.delete()  # SoftDeleteMixin.delete() under SOFT_DELETE=True -- soft delete
    assert not SourceCollection.objects.filter(pk=collection.pk).exists()
    assert SourceCollection.all_objects.filter(pk=collection.pk).exists(), (
        "fixture failed to produce a soft-deleted (not hard-deleted) row"
    )

    settings.SOFT_DELETE = False  # the platform default; the org sweep must not depend on this
    OrganizationManagementService().delete_organization(
        actor=actor, org_id=populated_org.pk
    )

    assert not SourceCollection.all_objects.filter(pk=collection.pk).exists()
    assert not DocumentContent.objects.filter(pk=content.pk).exists()


@pytest.mark.django_db
def test_cannot_delete_the_default_org(db, actor, _surviving_org):
    org = Organization.objects.create(name="Default Org", is_default=True)
    with pytest.raises(DefaultOrganizationNotDeletableError):
        OrganizationManagementService().preview_delete(
            actor=actor, org_id=org.pk
        )


@pytest.mark.django_db
def test_default_org_blocker_applies_in_real_mode_too(db, actor, _surviving_org):
    """The default-organization guard applies whether or not dry_run is set."""
    org = Organization.objects.create(name="Default Org Real", is_default=True)
    with pytest.raises(DefaultOrganizationNotDeletableError):
        OrganizationManagementService().delete_organization(
            actor=actor, org_id=org.pk
        )


@pytest.mark.django_db
def test_cannot_delete_the_last_org(db, actor):
    Organization.objects.all().delete()
    only = Organization.objects.create(name="Only Org")
    with pytest.raises(LastOrganizationError):
        OrganizationManagementService().preview_delete(
            actor=actor, org_id=only.pk
        )


@pytest.mark.django_db
def test_cannot_delete_the_last_active_org_even_if_an_inactive_one_exists(db, actor):
    """Deleting the only active org is refused even when an inactive org also exists."""
    Organization.objects.all().delete()
    active = Organization.objects.create(name="Only Active Org")
    Organization.objects.create(name="Inactive Org", is_active=False)

    with pytest.raises(LastOrganizationError):
        OrganizationManagementService().preview_delete(
            actor=actor, org_id=active.pk
        )


@pytest.mark.django_db
def test_org_report_includes_storage_totals(actor, populated_org, _surviving_org):
    """`storage_files` is the MinIO object count (2, per `_no_storage_calls`) plus the recording count (0, no recordings here)."""
    report = OrganizationManagementService().preview_delete(
        actor=actor, org_id=populated_org.pk
    )
    assert report.affected_resources.get("storage_files") == 2


@pytest.mark.django_db
def test_org_report_survives_storage_listing_failure(
    actor, populated_org, _surviving_org, _no_storage_calls
):
    """A `list_all_objects` failure degrades the storage count to None (contributing 0) instead of raising; with no recordings either, `storage_files` is simply absent."""
    _no_storage_calls.return_value.list_all_objects.side_effect = RuntimeError("minio down")

    report = OrganizationManagementService().preview_delete(
        actor=actor, org_id=populated_org.pk
    )

    assert "storage_files" not in report.affected_resources


@pytest.mark.django_db
def test_org_report_survives_storage_backend_construction_failure(
    actor, populated_org, _surviving_org, _no_storage_calls
):
    """A `get_storage_backend` construction failure also degrades to a 0 contribution instead of raising."""
    _no_storage_calls.side_effect = RuntimeError("bad credentials")

    report = OrganizationManagementService().preview_delete(
        actor=actor, org_id=populated_org.pk
    )

    assert "storage_files" not in report.affected_resources


@pytest.mark.django_db
def test_storage_purge_runs_after_a_real_delete(
    actor,
    populated_org,
    _surviving_org,
    _no_storage_calls,
    django_capture_on_commit_callbacks,
):
    with django_capture_on_commit_callbacks(execute=True):
        OrganizationManagementService().delete_organization(
            actor=actor, org_id=populated_org.pk
        )
    _no_storage_calls.return_value.delete_prefix.assert_called_once_with("")


@pytest.mark.django_db
def test_storage_failure_does_not_undo_the_delete(
    actor,
    populated_org,
    _surviving_org,
    _no_storage_calls,
    django_capture_on_commit_callbacks,
):
    _no_storage_calls.return_value.delete_prefix.side_effect = RuntimeError("minio down")

    with django_capture_on_commit_callbacks(execute=True):
        OrganizationManagementService().delete_organization(
            actor=actor, org_id=populated_org.pk
        )

    assert not Organization.objects.filter(pk=populated_org.pk).exists()


@pytest.mark.django_db
def test_storage_purge_does_not_short_circuit_on_a_folder_marker(
    mocker,
    actor,
    populated_org,
    _surviving_org,
    _no_storage_calls,
    django_capture_on_commit_callbacks,
):
    """A zero-byte `org_{id}/` marker must not divert the purge into a single-object delete."""
    from datetime import datetime, timezone
    from unittest.mock import patch

    from tables.services.storage_service.s3_backend import S3StorageBackend

    prefix = f"org_{populated_org.pk}/"
    with patch("tables.services.storage_service.s3_backend.boto3"):
        backend = S3StorageBackend(
            bucket_name="test",
            access_key="k",
            secret_key="s",
            organization_prefix=prefix,
            endpoint_url=None,
        )
    backend.client = mocker.MagicMock()
    # head_object succeeding is exactly the case that used to swallow the purge.
    backend.client.head_object.return_value = {"ContentLength": 0}
    paginator = mocker.MagicMock()
    paginator.paginate.return_value = [
        {
            "Contents": [
                {"Key": prefix, "Size": 0, "LastModified": datetime.now(timezone.utc)},
                {
                    "Key": f"{prefix}a.txt",
                    "Size": 10,
                    "LastModified": datetime.now(timezone.utc),
                },
            ]
        }
    ]
    backend.client.get_paginator.return_value = paginator
    _no_storage_calls.return_value = backend

    with django_capture_on_commit_callbacks(execute=True):
        OrganizationManagementService().delete_organization(
            actor=actor, org_id=populated_org.pk
        )

    backend.client.delete_object.assert_not_called()
    deleted_keys = {
        entry["Key"]
        for call in backend.client.delete_objects.call_args_list
        for entry in call.kwargs["Delete"]["Objects"]
    }
    assert deleted_keys == {prefix, f"{prefix}a.txt"}


@pytest.mark.django_db
def test_org_delete_clears_the_platform_default_config_cache(
    actor, populated_org, _surviving_org, django_capture_on_commit_callbacks
):
    """Platform defaults pointing at the org's configs are nulled, and the process cache stops serving the dead row."""
    from tables.models.base_models import DefaultBaseModel
    from tables.models.default_models import DefaultModels
    from tables.models.llm_models import LLMConfig

    config = LLMConfig.objects.create(custom_name="doomed-llm", org=populated_org)
    defaults = DefaultModels.load()
    defaults.agent_llm_config = config
    defaults.save()
    assert DefaultModels.load().agent_llm_config_id == config.pk

    with django_capture_on_commit_callbacks(execute=True):
        OrganizationManagementService().delete_organization(
            actor=actor, org_id=populated_org.pk
        )

    assert not LLMConfig.objects.filter(pk=config.pk).exists()
    assert DefaultModels.objects.get(pk=1).agent_llm_config_id is None
    assert DefaultModels not in DefaultBaseModel._load_cache
    assert DefaultModels.load().agent_llm_config_id is None
