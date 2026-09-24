"""A graph import must not be able to silently steal another org's webhook
path.

`WebhookTrigger.path` is globally unique on its own (see the `unique=True`
on `WebhookTrigger.path`) -- not scoped by `provider_type` -- because the
downstream `webhook` FastAPI service resolves inbound requests by bare path
with no org or provider discriminant -- a colliding path lets one org's
import stop a sibling org's webhook deliveries. Importing a graph whose
`WebhookTrigger` node declares a `path` already registered by a different
org must fail cleanly (a DRF `ValidationError`, not a raw `IntegrityError`
or a 500) and roll back the *entire* import -- no partially-created
Graph/nodes left behind.
"""

import pytest
from rest_framework.exceptions import ValidationError

from tables.models import Graph, PythonCode, WebhookTrigger, WebhookTriggerNode
from rbac.models import Organization
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.import_service import ImportService
from tables.import_export.schemas import ImportSettings


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B for webhook import collision test")


@pytest.fixture
def attacker_org(db):
    """The org doing the importing -- distinct from both the victim
    (`default_org`, which already legitimately owns the colliding path) and
    the org the crafted graph happens to have been authored in. Neither
    `find_existing`'s own-org reuse nor "it's my own path" legitimately
    explains away this import: it must be rejected purely because the path
    is claimed by someone else."""
    return Organization.objects.create(name="Attacker org for webhook import test")


def _build_source_graph(org, path):
    graph = Graph.objects.create(name="src-webhook-graph", org=org)
    trigger = WebhookTrigger.objects.create(path=path, org=org)
    code = PythonCode.objects.create(
        code="def main(): ...", entrypoint="main", libraries=""
    )
    WebhookTriggerNode.objects.create(
        graph=graph, node_name="wt", webhook_trigger=trigger, python_code=code
    )
    return graph


@pytest.mark.django_db
class TestWebhookTriggerImportPathCollision:
    def test_import_rolls_back_on_cross_org_path_collision(
        self, default_org, org_b, attacker_org, export_service
    ):
        # default_org (the victim) already legitimately owns this path.
        WebhookTrigger.objects.create(path="collision-path", org=default_org)

        # A graph authored in a third org, exported, then doctored to
        # declare the victim's path -- modeling an attacker-controlled
        # import payload (e.g. a hand-edited export file) rather than
        # relying on any particular UI flow.
        source_graph = _build_source_graph(org_b, path="attacker-own-path")
        export_data = export_service.export_entities(
            EntityType.GRAPH, [source_graph.id]
        )
        export_data[EntityType.WEBHOOK_TRIGGER][0]["path"] = "collision-path"

        graphs_before = Graph.objects.filter(org=attacker_org).count()
        triggers_before = WebhookTrigger.objects.filter(org=attacker_org).count()

        with pytest.raises(ValidationError):
            ImportService(entity_registry).import_data(
                export_data,
                EntityType.GRAPH,
                settings=ImportSettings(),
                org_id=attacker_org.id,
            )

        # No partial import: neither the graph nor any extra trigger row
        # was left behind in the importing org, and the victim's own row
        # is untouched.
        assert Graph.objects.filter(org=attacker_org).count() == graphs_before
        assert WebhookTrigger.objects.filter(org=attacker_org).count() == triggers_before
        assert (
            WebhookTrigger.objects.filter(
                org=default_org, path="collision-path"
            ).count()
            == 1
        )

    def test_import_succeeds_when_path_is_not_claimed_elsewhere(
        self, default_org, org_b, export_service
    ):
        """Once the *original* owner of the path (default_org) no longer
        claims it -- e.g. it deleted its own trigger -- the path is free
        and a cross-org import of a graph that used to reference it must
        succeed cleanly. (A path can never be "free" while its original
        owner still holds it: uniqueness is global, so re-importing the
        same graph into a second org while the source trigger still exists
        is expected to collide -- that's exactly the bug this constraint
        closes, and is covered by the collision test above.)
        """
        source_graph = _build_source_graph(default_org, path="collision-path")
        export_data = export_service.export_entities(
            EntityType.GRAPH, [source_graph.id]
        )
        WebhookTrigger.objects.filter(org=default_org, path="collision-path").delete()

        id_mapper, _ = ImportService(entity_registry).import_data(
            export_data,
            EntityType.GRAPH,
            settings=ImportSettings(),
            org_id=org_b.id,
        )

        created_graphs = id_mapper.get_created_ids(EntityType.GRAPH)
        assert created_graphs, "graph must be created in org_b"
        assert WebhookTrigger.objects.filter(
            path="collision-path", org=org_b
        ).exists()
