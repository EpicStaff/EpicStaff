"""Lowering SANDBOX_EXECUTION_TIMEOUT lowers the timeouts already stored on nodes.

Invariant: after every `migrate` (each django_app start), no node stores an
`execution_timeout` above the sandbox ceiling. Rows above it are stored as the
ceiling; rows at or below it, and every other field, are untouched. The clamp is
configuration, not an edit: the graph's `save_version` stays as it was, so an editor
that loaded the flow before the restart can still save it, and a node's
`content_hash` read after the clamp is accepted by the next write. It runs only for
the tables app's `post_migrate`, and skips a schema that has no `execution_timeout`
column (a migrate back to before it).
"""

import pytest
from django.apps import apps as installed_apps
from django.core.management.sql import emit_post_migrate_signal
from django.db import DEFAULT_DB_ALIAS, connection
from django.db.migrations.loader import MigrationLoader
from django.db.models.signals import post_migrate
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from tables.models import Graph
from tables.services.execution_timeout_ceiling_service import clamp_stored_execution_timeouts
from tests.execution_timeout_node_specs import (
    EXECUTION_TIMEOUT_NODE_SPEC_IDS,
    EXECUTION_TIMEOUT_NODE_SPECS,
)
from utils.logger import logger

CEILING_MINUTES = 5
ABOVE_CEILING_MINUTES = 9
BELOW_CEILING_MINUTES = 3
MIGRATION_BEFORE_THE_COLUMN = ("tables", "0268_merge_20261013_1631")


@pytest.fixture(params=EXECUTION_TIMEOUT_NODE_SPECS, ids=EXECUTION_TIMEOUT_NODE_SPEC_IDS)
def spec(request):
    return request.param


@pytest.fixture
def graph(default_org):
    return Graph.objects.create(name="execution-timeout-ceiling-clamp", org=default_org)


@pytest.fixture
def ceiling(settings):
    """Nodes are created under a higher ceiling, then the ceiling is lowered, the
    way an operator lowers SANDBOX_EXECUTION_TIMEOUT before a restart."""
    settings.SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES = ABOVE_CEILING_MINUTES
    yield settings
    settings.SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES = CEILING_MINUTES


def _lower_ceiling(settings):
    settings.SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES = CEILING_MINUTES


def _stored(spec, node) -> int:
    return spec.model._base_manager.values_list("execution_timeout", flat=True).get(pk=node.pk)


@pytest.fixture
def captured_info_logs():
    lines: list[str] = []
    sink_id = logger.add(lambda message: lines.append(message.record["message"]), level="INFO")
    yield lines
    logger.remove(sink_id)


@pytest.mark.django_db
class TestClamp:
    def test_only_rows_above_the_ceiling_are_lowered(self, spec, graph, ceiling):
        above = spec.create(graph, node_name="above", execution_timeout=ABOVE_CEILING_MINUTES)
        at = spec.create(graph, node_name="at", execution_timeout=CEILING_MINUTES)
        below = spec.create(graph, node_name="below", execution_timeout=BELOW_CEILING_MINUTES)
        _lower_ceiling(ceiling)

        clamped = clamp_stored_execution_timeouts(installed_apps, DEFAULT_DB_ALIAS)

        assert clamped == 1
        assert _stored(spec, above) == CEILING_MINUTES
        assert _stored(spec, at) == CEILING_MINUTES
        assert _stored(spec, below) == BELOW_CEILING_MINUTES

    def test_soft_deleted_rows_are_lowered_too(self, spec, graph, ceiling):
        node = spec.create(graph, execution_timeout=ABOVE_CEILING_MINUTES)
        spec.model._base_manager.filter(pk=node.pk).update(
            is_soft_deleted=True, soft_deleted_at=timezone.now()
        )
        _lower_ceiling(ceiling)

        clamp_stored_execution_timeouts(installed_apps, DEFAULT_DB_ALIAS)

        assert _stored(spec, node) == CEILING_MINUTES

    def test_nothing_above_the_ceiling_changes_nothing_and_logs_nothing(
        self, spec, graph, ceiling, captured_info_logs
    ):
        node = spec.create(graph, execution_timeout=BELOW_CEILING_MINUTES)
        updated_at_before = spec.model._base_manager.get(pk=node.pk).updated_at
        _lower_ceiling(ceiling)

        clamped = clamp_stored_execution_timeouts(installed_apps, DEFAULT_DB_ALIAS)

        assert clamped == 0
        assert spec.model._base_manager.get(pk=node.pk).updated_at == updated_at_before
        assert not [line for line in captured_info_logs if "execution timeout" in line]

    def test_clamping_logs_the_count(self, spec, graph, ceiling, captured_info_logs):
        spec.create(graph, node_name="first", execution_timeout=ABOVE_CEILING_MINUTES)
        spec.create(graph, node_name="second", execution_timeout=ABOVE_CEILING_MINUTES)
        _lower_ceiling(ceiling)

        clamp_stored_execution_timeouts(installed_apps, DEFAULT_DB_ALIAS)

        assert (
            f"Lowered 2 node execution timeout(s) to the sandbox ceiling of {CEILING_MINUTES} min."
            in captured_info_logs
        )

    def test_schema_without_the_column_is_skipped(self, spec, graph, ceiling):
        node = spec.create(graph, execution_timeout=ABOVE_CEILING_MINUTES)
        _lower_ceiling(ceiling)
        schema_before_the_column = (
            MigrationLoader(connection).project_state(MIGRATION_BEFORE_THE_COLUMN).apps
        )

        clamped = clamp_stored_execution_timeouts(schema_before_the_column, DEFAULT_DB_ALIAS)

        assert clamped == 0
        assert _stored(spec, node) == ABOVE_CEILING_MINUTES


@pytest.mark.django_db
class TestPostMigrate:
    def test_migrate_clamps_stored_timeouts(self, spec, graph, ceiling):
        node = spec.create(graph, execution_timeout=ABOVE_CEILING_MINUTES)
        _lower_ceiling(ceiling)

        # What `migrate` sends once it has applied the migrations.
        emit_post_migrate_signal(verbosity=0, interactive=False, db=DEFAULT_DB_ALIAS)

        assert _stored(spec, node) == CEILING_MINUTES

    def test_another_apps_post_migrate_does_not_clamp(self, spec, graph, ceiling):
        node = spec.create(graph, execution_timeout=ABOVE_CEILING_MINUTES)
        _lower_ceiling(ceiling)

        post_migrate.send(
            sender=installed_apps.get_app_config("rbac"),
            app_config=installed_apps.get_app_config("rbac"),
            verbosity=0,
            interactive=False,
            using=DEFAULT_DB_ALIAS,
            apps=installed_apps,
            plan=[],
        )

        assert _stored(spec, node) == ABOVE_CEILING_MINUTES


@pytest.mark.django_db
class TestEditorAfterTheClamp:
    def test_flow_loaded_before_the_clamp_still_saves(self, spec, graph, ceiling, auth_client):
        node = spec.create(graph, execution_timeout=ABOVE_CEILING_MINUTES)
        graph.refresh_from_db()
        save_version_loaded_by_the_editor = graph.save_version
        _lower_ceiling(ceiling)

        clamp_stored_execution_timeouts(installed_apps, DEFAULT_DB_ALIAS)

        graph.refresh_from_db()
        assert graph.save_version == save_version_loaded_by_the_editor
        response = auth_client.post(
            reverse("graphs-save-flow", args=[graph.id]),
            {
                "save_version": save_version_loaded_by_the_editor,
                spec.graph_list_key: [spec.request_body(graph, id=node.id, execution_timeout=2)],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        assert _stored(spec, node) == 2

    @pytest.mark.parametrize(
        "spec",
        [spec for spec in EXECUTION_TIMEOUT_NODE_SPECS if spec.id in ("python", "file-extractor", "audio-transcription")],
        ids=lambda spec: spec.id,
    )
    def test_content_hash_read_after_the_clamp_is_accepted(self, spec, graph, ceiling, auth_client):
        """Only these node endpoints return `content_hash`, so only their editors
        can send one back."""
        node = spec.create(graph, execution_timeout=ABOVE_CEILING_MINUTES)
        detail_url = reverse(f"{spec.basename}-detail", args=[node.id])
        hash_before_the_clamp = auth_client.get(detail_url).data["content_hash"]
        _lower_ceiling(ceiling)

        clamp_stored_execution_timeouts(installed_apps, DEFAULT_DB_ALIAS)

        hash_after_the_clamp = auth_client.get(detail_url).data["content_hash"]
        stale = auth_client.patch(
            detail_url, {"execution_timeout": 1, "content_hash": hash_before_the_clamp}, format="json"
        )
        fresh = auth_client.patch(
            detail_url, {"execution_timeout": 2, "content_hash": hash_after_the_clamp}, format="json"
        )
        assert stale.status_code == status.HTTP_409_CONFLICT, stale.content
        assert fresh.status_code == status.HTTP_200_OK, fresh.content
        assert _stored(spec, node) == 2
