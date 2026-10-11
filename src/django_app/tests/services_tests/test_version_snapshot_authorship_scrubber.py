"""VersionSnapshotAuthorshipScrubber clears a user from the node authorship versions recorded."""

from datetime import UTC, datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from rbac.authorship import record_last_edit
from rbac.models import OrganizationUser
from tables.graph_versioning import snapshot_authorship
from tables.graph_versioning.services import GraphVersioningService
from tables.graph_versioning.snapshot_authorship import VersionSnapshotAuthorshipScrubber
from tables.models import Graph, GraphVersion
from tables.models.graph_models import AgentNode
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

CREATED_AT = "2024-01-02T03:04:05+00:00"
EDITED_AT = "2024-02-03T04:05:06+00:00"

# Path to every slot of a snapshot that records a user.
RECORDED_USER_SLOTS = {
    "node_authorship": ("node_authorship", "11", "created_by"),
    "node_last_edit": ("node_last_edit", "11", "edited_by"),
}


@pytest.fixture
def author(db, django_user_model):
    return django_user_model.objects.create_user(
        email="scrubbed-author@example.com", password="StrongPass123!"
    )


@pytest.fixture
def colleague(db, django_user_model):
    return django_user_model.objects.create_user(
        email="kept-colleague@example.com", password="StrongPass123!"
    )


def _snapshot_recording(
    user_id_by_slot: dict[str, int | None], *, default_user_id: int | None
) -> dict:
    """A snapshot with one node recording `default_user_id` in every slot but those given."""
    snapshot = {
        "nodes": [],
        "node_authorship": {"11": {"created_by": default_user_id, "created_at": CREATED_AT}},
        "node_last_edit": {"11": {"edited_by": default_user_id, "edited_at": EDITED_AT}},
    }
    for slot, user_id in user_id_by_slot.items():
        *parents, key = RECORDED_USER_SLOTS[slot]
        entry = snapshot
        for parent in parents:
            entry = entry[parent]
        entry[key] = user_id
    return snapshot


def _version(org, *, name, snapshot, soft_deleted_flow=False, soft_deleted_version=False):
    flow = Graph.objects.create(
        name=name,
        org=org,
        is_soft_deleted=soft_deleted_flow,
        soft_deleted_at=timezone.now() if soft_deleted_flow else None,
    )
    return GraphVersion.objects.create(
        graph=flow,
        name=name,
        snapshot=snapshot,
        is_soft_deleted=soft_deleted_version,
        soft_deleted_at=timezone.now() if soft_deleted_version else None,
    )


def _stored_snapshot(version) -> dict:
    return GraphVersion.all_objects.get(pk=version.pk).snapshot


def _recording_everywhere(user_id: int) -> dict:
    return _snapshot_recording({}, default_user_id=user_id)


def _cleared_everywhere(user_id: int) -> dict:
    return _snapshot_recording(dict.fromkeys(RECORDED_USER_SLOTS), default_user_id=user_id)


@pytest.mark.django_db
@pytest.mark.parametrize("slot", list(RECORDED_USER_SLOTS))
def test_scrub_clears_the_user_from_the_one_slot_recording_them(acme, author, colleague, slot):
    version = _version(
        acme,
        name="one-slot",
        snapshot=_snapshot_recording({slot: author.id}, default_user_id=colleague.id),
    )

    scrubbed = VersionSnapshotAuthorshipScrubber().scrub_in_organization(
        user_id=author.id, org_id=acme.id
    )

    assert scrubbed == 1
    assert _stored_snapshot(version) == _snapshot_recording(
        {slot: None}, default_user_id=colleague.id
    )


@pytest.mark.django_db
def test_scrub_in_organization_nulls_every_slot_and_keeps_the_times(acme, author):
    version = _version(acme, name="authored", snapshot=_recording_everywhere(author.id))

    scrubbed = VersionSnapshotAuthorshipScrubber().scrub_in_organization(
        user_id=author.id, org_id=acme.id
    )

    assert scrubbed == 1
    assert _stored_snapshot(version) == _cleared_everywhere(author.id)


@pytest.mark.django_db
def test_scrub_in_organization_leaves_other_users_untouched(acme, author, colleague):
    colleague_only = _version(
        acme, name="colleague-only", snapshot=_recording_everywhere(colleague.id)
    )

    scrubbed = VersionSnapshotAuthorshipScrubber().scrub_in_organization(
        user_id=author.id, org_id=acme.id
    )

    assert scrubbed == 0
    assert _stored_snapshot(colleague_only) == _recording_everywhere(colleague.id)


@pytest.mark.django_db
def test_scrub_in_organization_leaves_versions_of_other_organizations_untouched(
    acme, beta, author
):
    acme_version = _version(acme, name="acme-flow", snapshot=_recording_everywhere(author.id))
    beta_version = _version(beta, name="beta-flow", snapshot=_recording_everywhere(author.id))

    VersionSnapshotAuthorshipScrubber().scrub_in_organization(user_id=author.id, org_id=acme.id)

    assert _stored_snapshot(acme_version) == _cleared_everywhere(author.id)
    assert _stored_snapshot(beta_version) == _recording_everywhere(author.id)


@pytest.mark.django_db
def test_scrub_in_every_organization_clears_the_user_in_all_of_them(acme, beta, author):
    acme_version = _version(acme, name="acme-flow", snapshot=_recording_everywhere(author.id))
    beta_version = _version(beta, name="beta-flow", snapshot=_recording_everywhere(author.id))

    scrubbed = VersionSnapshotAuthorshipScrubber().scrub_in_every_organization(user_id=author.id)

    assert scrubbed == 2
    assert _stored_snapshot(acme_version) == _cleared_everywhere(author.id)
    assert _stored_snapshot(beta_version) == _cleared_everywhere(author.id)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "soft_deleted", ["soft_deleted_version", "soft_deleted_flow"], ids=["version", "flow"]
)
def test_scrub_covers_soft_deleted_versions_and_versions_of_soft_deleted_flows(
    acme, author, soft_deleted
):
    version = _version(
        acme, name="deleted", snapshot=_recording_everywhere(author.id), **{soft_deleted: True}
    )

    scrubbed = VersionSnapshotAuthorshipScrubber().scrub_in_organization(
        user_id=author.id, org_id=acme.id
    )

    assert scrubbed == 1
    assert _stored_snapshot(version) == _cleared_everywhere(author.id)


@pytest.mark.django_db
def test_scrub_handles_legacy_snapshots_without_node_authorship(acme, author):
    without_node_last_edit = _version(
        acme,
        name="node-authorship-only",
        snapshot={
            "nodes": [],
            "node_authorship": {"11": {"created_by": author.id, "created_at": CREATED_AT}},
        },
    )
    without_any_authorship = _version(acme, name="oldest", snapshot={"nodes": []})

    scrubbed = VersionSnapshotAuthorshipScrubber().scrub_in_organization(
        user_id=author.id, org_id=acme.id
    )

    assert scrubbed == 1
    assert _stored_snapshot(without_node_last_edit) == {
        "nodes": [],
        "node_authorship": {"11": {"created_by": None, "created_at": CREATED_AT}},
    }
    assert _stored_snapshot(without_any_authorship) == {"nodes": []}


@pytest.mark.django_db
def test_scrub_ignores_the_user_id_outside_the_authorship_blocks(acme, author):
    """Node data can hold any integer (e.g. a node id equal to the user id); only the
    authorship blocks name users."""
    snapshot = {"nodes": [{"id": author.id, "created_by": author.id}]}
    version = _version(acme, name="unrelated-ids", snapshot=snapshot)

    scrubbed = VersionSnapshotAuthorshipScrubber().scrub_in_organization(
        user_id=author.id, org_id=acme.id
    )

    assert scrubbed == 0
    assert _stored_snapshot(version) == snapshot


@pytest.mark.django_db
def test_database_filter_selects_only_versions_recording_the_user(acme, author, colleague):
    """Snapshots that do not record the user are never loaded."""
    recording = {
        slot: _version(
            acme,
            name=f"records-{slot}",
            snapshot=_snapshot_recording({slot: author.id}, default_user_id=colleague.id),
        )
        for slot in RECORDED_USER_SLOTS
    }
    _version(acme, name="colleague-only", snapshot=_recording_everywhere(colleague.id))
    _version(
        acme,
        name="id-outside-authorship",
        snapshot={"nodes": [{"id": author.id, "created_by": author.id}]},
    )

    selected = GraphVersion.all_objects.filter(
        snapshot_authorship._SnapshotMatchesJsonpath(
            snapshot_authorship._RECORDS_USER_JSONPATH, {"user_id": author.id}
        )
    )

    assert set(selected.values_list("id", flat=True)) == {
        version.id for version in recording.values()
    }


@pytest.mark.django_db
def test_scrub_rewrites_every_recording_version_across_batches(acme, author, monkeypatch):
    monkeypatch.setattr(snapshot_authorship, "_SCRUB_BATCH_SIZE", 2)
    versions = [
        _version(acme, name=f"batched-{index}", snapshot=_recording_everywhere(author.id))
        for index in range(5)
    ]

    scrubbed = VersionSnapshotAuthorshipScrubber().scrub_in_organization(
        user_id=author.id, org_id=acme.id
    )

    assert scrubbed == 5
    for version in versions:
        assert _stored_snapshot(version) == _cleared_everywhere(author.id)


# ---- contract with GraphVersioningService.save_version ----


def _leaf_values(value) -> list:
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _leaf_values(item)]
    return [value]


@pytest.mark.django_db
def test_scrub_clears_every_slot_a_saved_version_records(acme, author):
    """Guards the snapshot keys the scrubber knows against the ones save_version writes."""
    flow = Graph.objects.create(name="saved-flow", org=acme)
    node = AgentNode.objects.create(graph=flow, node_name="agent", created_by=author)
    edited_at = datetime(2024, 3, 4, 5, 6, 7, tzinfo=UTC)
    record_last_edit(node, author, edited_at=edited_at)
    version = GraphVersioningService().save_version(flow, name="v1")
    for block in ("node_authorship", "node_last_edit"):
        assert author.id in _leaf_values(version.snapshot[block]), block

    VersionSnapshotAuthorshipScrubber().scrub_in_organization(user_id=author.id, org_id=acme.id)

    scrubbed_snapshot = _stored_snapshot(version)
    for block in ("node_authorship", "node_last_edit"):
        assert author.id not in _leaf_values(scrubbed_snapshot[block]), block
    assert scrubbed_snapshot["node_last_edit"][str(node.id)]["edited_at"] == edited_at.isoformat()


@pytest.mark.django_db
def test_scrub_without_recorded_user_returns_zero(acme, author):
    assert (
        VersionSnapshotAuthorshipScrubber().scrub_in_organization(user_id=author.id, org_id=acme.id)
        == 0
    )


@pytest.mark.django_db
def test_scrub_locks_the_versions_it_rewrites(acme, author):
    """Two scrubs of the same version must not overwrite each other's changes."""
    _version(acme, name="locked", snapshot=_recording_everywhere(author.id))

    with CaptureQueriesContext(connection) as context:
        VersionSnapshotAuthorshipScrubber().scrub_in_organization(
            user_id=author.id, org_id=acme.id
        )

    [select] = [
        query["sql"] for query in context.captured_queries if "jsonb_path_match" in query["sql"]
    ]
    assert 'FOR UPDATE OF "tables_graphversion"' in select


# ---- outside memberships ----


@pytest.mark.django_db
def test_scrub_outside_memberships_clears_the_user_only_where_they_are_not_a_member(
    acme, beta, author, role_member
):
    OrganizationUser.objects.create(user=author, org=acme, role=role_member)
    member_org_version = _version(
        acme, name="member-org-flow", snapshot=_recording_everywhere(author.id)
    )
    other_org_version = _version(
        beta, name="other-org-flow", snapshot=_recording_everywhere(author.id)
    )

    scrubbed = VersionSnapshotAuthorshipScrubber().scrub_outside_memberships(user_id=author.id)

    assert scrubbed == 1
    assert _stored_snapshot(member_org_version) == _recording_everywhere(author.id)
    assert _stored_snapshot(other_org_version) == _cleared_everywhere(author.id)


@pytest.mark.django_db
def test_scrub_outside_memberships_of_a_user_without_memberships_clears_every_org(
    acme, beta, author, colleague
):
    acme_version = _version(acme, name="acme-flow", snapshot=_recording_everywhere(author.id))
    beta_version = _version(
        beta,
        name="beta-flow",
        snapshot=_snapshot_recording({"node_last_edit": author.id}, default_user_id=colleague.id),
        soft_deleted_version=True,
    )

    scrubbed = VersionSnapshotAuthorshipScrubber().scrub_outside_memberships(user_id=author.id)

    assert scrubbed == 2
    assert _stored_snapshot(acme_version) == _cleared_everywhere(author.id)
    assert _stored_snapshot(beta_version) == _snapshot_recording(
        {"node_last_edit": None}, default_user_id=colleague.id
    )


# ---- every user ----


@pytest.mark.django_db
def test_scrub_every_user_clears_every_recorded_user_in_every_org_keeping_the_times(
    acme, beta, author, colleague
):
    mixed = _version(
        acme,
        name="mixed",
        snapshot=_snapshot_recording({"node_last_edit": colleague.id}, default_user_id=author.id),
    )
    other_org = _version(beta, name="other-org", snapshot=_recording_everywhere(colleague.id))
    deleted = _version(
        acme,
        name="deleted",
        snapshot=_recording_everywhere(author.id),
        soft_deleted_version=True,
    )
    unauthored = _version(beta, name="unauthored", snapshot=_cleared_everywhere(None))
    legacy = _version(acme, name="legacy", snapshot={"nodes": []})

    scrubbed = VersionSnapshotAuthorshipScrubber().scrub_every_user()

    assert scrubbed == 3
    for version in (mixed, other_org, deleted, unauthored):
        assert _stored_snapshot(version) == _cleared_everywhere(None)
    assert _stored_snapshot(legacy) == {"nodes": []}
