"""Renaming a version writes only its name and description."""

import pytest

from rbac.governance.authorship import VersionSnapshotAuthorshipScrubber
from tables.graph_versioning.serializers import GraphVersionUpdateSerializer
from tables.models import Graph, GraphVersion
from tables.models.graph_models import AgentNode
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.mark.django_db
def test_renaming_a_version_loaded_before_a_scrub_keeps_the_scrubbed_snapshot(
    service, acme, member_only
):
    flow = Graph.objects.create(name="renamed-flow", org=acme)
    AgentNode.objects.create(graph=flow, node_name="agent", created_by=member_only)
    version = service.save_version(flow, name="v1")
    loaded_version = GraphVersion.objects.get(pk=version.pk)
    VersionSnapshotAuthorshipScrubber().scrub_in_organization(
        user_id=member_only.id, org_id=acme.id
    )

    serializer = GraphVersionUpdateSerializer(
        loaded_version, data={"name": "renamed", "description": "after scrub"}, partial=True
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()

    stored = GraphVersion.objects.get(pk=version.pk)
    assert (stored.name, stored.description) == ("renamed", "after scrub")
    assert {entry["created_by"] for entry in stored.snapshot["node_authorship"].values()} == {None}
