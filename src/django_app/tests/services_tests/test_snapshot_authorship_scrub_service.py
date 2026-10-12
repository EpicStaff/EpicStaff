"""SnapshotAuthorshipScrubService runs every registered snapshot authorship scrubber."""

import pytest

from rbac.governance import authorship
from rbac.governance.authorship import (
    SnapshotAuthorshipScrubService,
    register_snapshot_scrubber,
    snapshot_scrubbers,
)
from tables.graph_versioning.snapshot_authorship import VersionSnapshotAuthorshipScrubber
from tables.models import Graph, GraphVersion
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


class _CountingScrubber:
    """A scrubber that records each call and reports a fixed number of rewritten snapshots."""

    def __init__(self, rewritten: int):
        self.rewritten = rewritten
        self.calls = []

    def scrub_in_organization(self, user_id, org_id):
        self.calls.append(("scrub_in_organization", {"user_id": user_id, "org_id": org_id}))
        return self.rewritten

    def scrub_in_every_organization(self, user_id):
        self.calls.append(("scrub_in_every_organization", {"user_id": user_id}))
        return self.rewritten

    def scrub_outside_memberships(self, user_id):
        self.calls.append(("scrub_outside_memberships", {"user_id": user_id}))
        return self.rewritten

    def scrub_every_user(self):
        self.calls.append(("scrub_every_user", {}))
        return self.rewritten


class _OtherCountingScrubber(_CountingScrubber):
    """A second scrubber type, so both can be registered side by side."""


@pytest.fixture
def registered_scrubbers(monkeypatch):
    """Replace the registered scrubbers with the given ones for the duration of a test."""

    def _replace(*scrubbers):
        monkeypatch.setattr(authorship, "_snapshot_scrubbers", list(scrubbers))

    return _replace


def test_version_snapshot_scrubber_is_registered_after_app_load():
    registered_types = [type(scrubber) for scrubber in snapshot_scrubbers()]

    assert registered_types.count(VersionSnapshotAuthorshipScrubber) == 1


def test_registering_the_same_scrubber_type_twice_is_refused():
    registered_before = snapshot_scrubbers()

    with pytest.raises(ValueError):
        register_snapshot_scrubber(VersionSnapshotAuthorshipScrubber())

    assert snapshot_scrubbers() == registered_before


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("scrub_in_organization", {"user_id": 7, "org_id": 3}),
        ("scrub_in_every_organization", {"user_id": 7}),
        ("scrub_outside_memberships", {"user_id": 7}),
        ("scrub_every_user", {}),
    ],
)
def test_each_operation_runs_every_registered_scrubber_and_sums_their_counts(
    registered_scrubbers, operation, arguments
):
    first, second = _CountingScrubber(rewritten=2), _OtherCountingScrubber(rewritten=3)
    registered_scrubbers(first, second)

    total = getattr(SnapshotAuthorshipScrubService(), operation)(**arguments)

    assert total == 5
    assert first.calls == [(operation, arguments)]
    assert second.calls == [(operation, arguments)]


@pytest.mark.django_db
def test_operations_rewrite_nothing_without_registered_scrubbers(registered_scrubbers):
    registered_scrubbers()

    assert SnapshotAuthorshipScrubService().scrub_every_user() == 0


@pytest.mark.django_db
def test_registered_version_scrubber_counts_add_to_other_scrubbers(
    registered_scrubbers, acme, member_only
):
    flow = Graph.objects.create(name="scrubbed-flow", org=acme)
    version = GraphVersion.objects.create(
        graph=flow,
        name="v1",
        snapshot={"node_authorship": {"1": {"created_by": member_only.id, "created_at": None}}},
    )
    registered_scrubbers(*snapshot_scrubbers(), _CountingScrubber(rewritten=3))

    total = SnapshotAuthorshipScrubService().scrub_in_organization(
        user_id=member_only.id, org_id=acme.id
    )

    assert total == 4
    version.refresh_from_db()
    assert version.snapshot["node_authorship"]["1"]["created_by"] is None
