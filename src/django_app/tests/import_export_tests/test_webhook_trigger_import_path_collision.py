"""Importing a webhook trigger whose path another org already holds.

`WebhookTrigger.path` is globally unique because the `webhook` service
resolves inbound requests by bare path. An import must never take over or
disturb the owner's trigger, and it must not fail either: the importing org
gets a trigger under a free org-suffixed path, and its nodes point at that
trigger. A same-org trigger with the path, or with the org-suffixed path an
earlier import gave it, is reused.
"""

import copy

import pytest

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.import_service import ImportService
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.models import Graph, PythonCode, WebhookTrigger, WebhookTriggerNode
from tables.services.webhook_trigger_service import (
    WEBHOOK_TRIGGER_PATH_MAX_LENGTH,
    find_available_path,
    organization_suffixed_path,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _build_source_graph(org, path):
    graph = Graph.objects.create(name="src-webhook-graph", org=org)
    trigger = WebhookTrigger.objects.create(path=path, org=org)
    code = PythonCode.objects.create(code="def main(): ...", entrypoint="main", libraries="")
    node = WebhookTriggerNode.objects.create(
        graph=graph, node_name="wt", webhook_trigger=trigger, python_code=code
    )
    return graph, node


def _import_graph(export_data, org):
    # The import consumes its payload in place, so each import gets its own copy.
    id_mapper, _ = ImportService(entity_registry).import_data(
        copy.deepcopy(export_data),
        EntityType.GRAPH,
        settings=ImportSettings(),
        org_id=org.id,
    )
    graph_id = id_mapper.get_created_ids(EntityType.GRAPH)[0]
    return WebhookTriggerNode.objects.select_related("webhook_trigger").get(graph_id=graph_id)


@pytest.mark.django_db
class TestWebhookTriggerImportPathCollision:
    def test_cross_org_collision_imports_under_org_suffixed_path(
        self, acme, beta, export_service
    ):
        source_graph, source_node = _build_source_graph(acme, path="collision-path")
        export_data = export_service.export_entities(EntityType.GRAPH, [source_graph.id])

        imported_node = _import_graph(export_data, beta)

        imported_trigger = imported_node.webhook_trigger
        assert imported_trigger.org_id == beta.id
        assert imported_trigger.path == f"collision-path-org{beta.id}"
        assert imported_trigger.id != source_node.webhook_trigger_id
        # The owner's trigger is untouched.
        owner_trigger = WebhookTrigger.objects.get(path="collision-path")
        assert owner_trigger.id == source_node.webhook_trigger_id
        assert owner_trigger.org_id == acme.id

    def test_same_org_import_reuses_existing_trigger(self, acme, export_service):
        source_graph, source_node = _build_source_graph(acme, path="own-path")
        export_data = export_service.export_entities(EntityType.GRAPH, [source_graph.id])
        triggers_before = WebhookTrigger.objects.count()

        imported_node = _import_graph(export_data, acme)

        assert imported_node.webhook_trigger_id == source_node.webhook_trigger_id
        assert WebhookTrigger.objects.count() == triggers_before

    def test_reimport_into_same_org_reuses_renamed_trigger(self, acme, beta, export_service):
        source_graph, _ = _build_source_graph(acme, path="popular-path")
        export_data = export_service.export_entities(EntityType.GRAPH, [source_graph.id])

        first_trigger = _import_graph(export_data, beta).webhook_trigger
        second_trigger = _import_graph(export_data, beta).webhook_trigger

        assert first_trigger.path == f"popular-path-org{beta.id}"
        assert second_trigger.id == first_trigger.id
        assert WebhookTrigger.objects.filter(org=beta).count() == 1
        assert WebhookTrigger.objects.filter(path__startswith="popular-path").count() == 2

    def test_collisions_in_different_orgs_get_distinct_paths(
        self, acme, beta, default_org, export_service
    ):
        source_graph, _ = _build_source_graph(acme, path="popular-path")
        export_data = export_service.export_entities(EntityType.GRAPH, [source_graph.id])

        beta_trigger = _import_graph(export_data, beta).webhook_trigger
        default_org_trigger = _import_graph(export_data, default_org).webhook_trigger

        assert beta_trigger.path == f"popular-path-org{beta.id}"
        assert beta_trigger.org_id == beta.id
        assert default_org_trigger.path == f"popular-path-org{default_org.id}"
        assert default_org_trigger.org_id == default_org.id

    def test_org_suffixed_path_squatted_by_other_org_is_not_reused(
        self, acme, beta, export_service
    ):
        source_graph, _ = _build_source_graph(acme, path="squat-path")
        squatter = WebhookTrigger.objects.create(path=f"squat-path-org{beta.id}", org=acme)
        export_data = export_service.export_entities(EntityType.GRAPH, [source_graph.id])

        imported_trigger = _import_graph(export_data, beta).webhook_trigger

        assert imported_trigger.id != squatter.id
        assert imported_trigger.org_id == beta.id
        assert imported_trigger.path == f"squat-path-org{beta.id}-2"
        squatter.refresh_from_db()
        assert squatter.org_id == acme.id
        assert squatter.path == f"squat-path-org{beta.id}"

    def test_free_path_from_other_org_export_stays_unchanged(
        self, acme, beta, export_service
    ):
        source_graph, source_node = _build_source_graph(acme, path="free-path")
        export_data = export_service.export_entities(EntityType.GRAPH, [source_graph.id])
        # The exporting org renames its trigger, so the exported path is free again.
        WebhookTrigger.objects.filter(id=source_node.webhook_trigger_id).update(
            path="free-path-renamed"
        )

        imported_trigger = _import_graph(export_data, beta).webhook_trigger

        assert imported_trigger.path == "free-path"
        assert imported_trigger.org_id == beta.id
        assert imported_trigger.id != source_node.webhook_trigger_id

    def test_long_colliding_path_is_truncated_and_reused_on_reimport(
        self, acme, beta, export_service
    ):
        long_path = "a" * WEBHOOK_TRIGGER_PATH_MAX_LENGTH
        source_graph, _ = _build_source_graph(acme, path=long_path)
        export_data = export_service.export_entities(EntityType.GRAPH, [source_graph.id])

        first_trigger = _import_graph(export_data, beta).webhook_trigger
        second_trigger = _import_graph(export_data, beta).webhook_trigger

        suffix = f"-org{beta.id}"
        assert len(first_trigger.path) == WEBHOOK_TRIGGER_PATH_MAX_LENGTH
        assert first_trigger.path == long_path[: -len(suffix)] + suffix
        assert second_trigger.id == first_trigger.id

    def test_partial_import_renames_cross_org_colliding_path(self, acme, beta):
        _, source_node = _build_source_graph(acme, path="pasted-path")
        export_result = GraphPartialExportService(entity_registry).export(
            [NodeRef(entity_type=EntityType.WEBHOOK_TRIGGER_NODE, node_id=source_node.id)]
        )
        assert not export_result.has_errors, export_result.errors
        target_graph = Graph.objects.create(name="paste-target", org=beta)

        PartialImportService(entity_registry).import_data(
            export_data=export_result.data, graph=target_graph, org_id=beta.id
        )

        pasted_node = WebhookTriggerNode.objects.select_related("webhook_trigger").get(
            graph=target_graph
        )
        assert pasted_node.webhook_trigger.org_id == beta.id
        assert pasted_node.webhook_trigger.path == f"pasted-path-org{beta.id}"
        assert WebhookTrigger.objects.get(path="pasted-path").org_id == acme.id


@pytest.mark.django_db
class TestFindAvailablePath:
    def test_free_path_is_returned_unchanged(self, beta):
        assert find_available_path("free-path", beta.id) == "free-path"

    def test_taken_suffixed_path_moves_to_next_counter(self, acme, beta):
        WebhookTrigger.objects.create(path="busy", org=acme)
        # Another org happens to hold the literal first-choice rename target.
        WebhookTrigger.objects.create(path=f"busy-org{beta.id}", org=acme)

        assert find_available_path("busy", beta.id) == f"busy-org{beta.id}-2"

    def test_long_path_counter_suffix_is_kept_whole(self, acme, beta):
        long_path = "b" * WEBHOOK_TRIGGER_PATH_MAX_LENGTH
        WebhookTrigger.objects.create(path=long_path, org=acme)
        WebhookTrigger.objects.create(path=organization_suffixed_path(long_path, beta.id), org=acme)

        counter_suffix = f"-org{beta.id}-2"
        result = find_available_path(long_path, beta.id)

        assert len(result) == WEBHOOK_TRIGGER_PATH_MAX_LENGTH
        assert result == long_path[: -len(counter_suffix)] + counter_suffix


@pytest.mark.django_db
class TestWebhookTriggerFindExisting:
    def _find_existing(self, path, org_id):
        strategy = entity_registry.get_strategy(EntityType.WEBHOOK_TRIGGER)
        return strategy.find_existing({"path": path}, IDMapper(), org_id=org_id)

    def test_exact_path_is_preferred_over_org_suffixed_rename(self, beta):
        exact = WebhookTrigger.objects.create(path="both", org=beta)
        WebhookTrigger.objects.create(path=f"both-org{beta.id}", org=beta)

        assert self._find_existing("both", beta.id) == exact

    def test_org_suffixed_rename_of_own_org_is_found(self, acme, beta):
        WebhookTrigger.objects.create(path="renamed", org=acme)
        renamed = WebhookTrigger.objects.create(path=f"renamed-org{beta.id}", org=beta)

        assert self._find_existing("renamed", beta.id) == renamed

    def test_other_orgs_triggers_are_never_returned(self, acme, beta):
        WebhookTrigger.objects.create(path="foreign", org=acme)
        WebhookTrigger.objects.create(path=f"foreign-org{beta.id}", org=acme)

        assert self._find_existing("foreign", beta.id) is None

    def test_without_org_only_the_exact_path_matches(self, beta):
        WebhookTrigger.objects.create(path=f"unscoped-org{beta.id}", org=beta)

        assert self._find_existing("unscoped", None) is None
