from dataclasses import dataclass
from typing import TypedDict

from django.db import transaction

from tables.graph_versioning.manager import GraphVersioningManager
from tables.import_export.constants import IMPORT_VERSION
from tables.models import (
    Graph,
    GraphVersion,
    Label,
)

# Graph-level ``metadata`` in snapshots saved before the secret FKs landed can carry node data
# with plaintext credentials (e.g. a Telegram trigger's bot key). The importer nulls them on the
# way in (``GraphStrategy.update_metadata``), but stored snapshots were never scrubbed.
# Keyed on field name, like migration 0211, so any depth and node type is covered.
_PLAINTEXT_SECRET_FIELD_NAMES = frozenset(
    {"telegram_bot_api_key", "api_key", "auth", "rt_api_key", "transcript_api_key"}
)


def _scrub_plaintext_secrets(value):
    if isinstance(value, dict):
        return {
            key: None if key in _PLAINTEXT_SECRET_FIELD_NAMES else _scrub_plaintext_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub_plaintext_secrets(item) for item in value]
    return value


@dataclass(frozen=True)
class PreparedVersion:
    """A version snapshot converted and filtered against the dependencies that still exist.

    Attributes:
        converted_snapshot: The stored snapshot upgraded to ``IMPORT_VERSION``, before
            any filtering. Still carries ``name`` and ``secret_declarations``.
        filtered_snapshot: ``converted_snapshot`` with missing-dependency FKs nulled and
            unsupported nodes, plus the edges touching them, removed.
        available_dependencies: Dependency ids that still exist, keyed by
            ``EntityType.value``.
        filter_warnings: Warnings produced while filtering.
    """

    converted_snapshot: dict
    filtered_snapshot: dict
    available_dependencies: dict[str, list[int]]
    filter_warnings: tuple[dict, ...]


class VersionPreview(TypedDict):
    snapshot: dict
    warnings: list[dict]


class GraphVersioningService:
    def __init__(self):
        self._manager = GraphVersioningManager()

    @transaction.atomic
    def save_version(self, graph: Graph, name: str, description: str = "") -> GraphVersion:
        """
        Create a named version snapshot of the given graph.
        """
        snapshot = self._manager.create_snapshot(graph)
        snapshot["version"] = IMPORT_VERSION
        snapshot["secret_declarations"] = self._manager.collect_secret_declarations(graph=graph)
        dependencies = self._manager.collect_dependencies(graph)

        return GraphVersion.objects.create(
            graph=graph,
            name=name,
            description=description,
            snapshot=snapshot,
            dependencies=dependencies,
        )

    @transaction.atomic
    def create_graph_from_version(self, version: GraphVersion) -> dict:
        """
        Create a brand-new Graph from a version snapshot.
        The new graph is fully independent — own id/uuid, zero GraphVersion rows.
        """
        source_graph = version.graph
        prepared = self._prepare(version)
        warnings = list(prepared.filter_warnings)

        graph_name = prepared.converted_snapshot.get("name", "Flow")
        new_graph, node_mapper = self._manager.create_graph_from_snapshot(
            prepared.filtered_snapshot,
            prepared.available_dependencies,
            graph_name=graph_name,
            version_name=version.name,
            org_id=source_graph.org_id,
        )

        # Copy labels from source graph
        new_graph.labels.set(source_graph.labels.filter(scope=Label.Scope.FLOW))

        warnings.extend(
            self._manager.restore_secret_declarations(
                graph=new_graph,
                declarations=prepared.converted_snapshot.get("secret_declarations"),
                node_mapper=node_mapper,
            )
        )

        self._manager.change_old_warnings_ids(warnings, node_mapper)

        return {
            "created": True,
            "graph_id": new_graph.id,
            "warnings": warnings,
        }

    def preview_version(self, version: GraphVersion) -> VersionPreview:
        """Return the snapshot that restoring or creating a graph from ``version`` would apply.

        Runs the same conversion and dependency filtering as ``restore_version`` and
        ``create_graph_from_version``, then stops: nothing is persisted and no ids are
        consumed. Only reads the database to check which dependencies still exist.

        Secret declarations are not re-linked, so the ``secret_declaration_dropped``
        warnings that a restore reports for deleted secrets are absent here — a preview
        with no warnings can still produce warnings on restore.

        Credential-named fields in the graph-level ``metadata`` are nulled, since old
        snapshots can hold them in plaintext.

        Returns:
            ``snapshot``: the filtered snapshot, with the version's original node ids.
            ``warnings``: the dependency-filtering warnings, keyed by those same ids.
        """
        prepared = self._prepare(version)
        snapshot = prepared.filtered_snapshot
        if "metadata" in snapshot:
            snapshot = {**snapshot, "metadata": _scrub_plaintext_secrets(snapshot["metadata"])}
        return {
            "snapshot": snapshot,
            "warnings": list(prepared.filter_warnings),
        }

    @transaction.atomic
    def restore_version(
        self,
        version: GraphVersion,
        *,
        expected_save_version: int,
        backup: bool = False,
    ) -> dict:
        """
        Restore a graph to the state captured in ``version``.

        The entire operation runs inside a single ``@transaction.atomic`` block.
        Any exception raised during restoration rolls back all database changes —
        including the auto-backup row — and propagates to the caller; the dict is
        never returned in that case.

        Parameters
        ----------
        version:
            The ``GraphVersion`` snapshot to restore from.
        backup:
            When ``True``, a named ``GraphVersion`` snapshot of the *current*
            graph state is created before the restore takes place, so the
            caller can undo the operation if needed.

        Returns
        -------
        dict with keys:

        - ``restored`` (bool): always ``True`` when returned.
        - ``graph_id`` (int): primary key of the graph that was restored.
        - ``warnings`` (list): dependency warnings produced during restoration
          (e.g. nodes whose dependencies were not found and were therefore
          skipped/fk nulled from the snapshot).
        - ``auto_backup_version_id`` (int | None): primary key of the
          auto-backup ``GraphVersion`` row created when ``backup=True``.
          This key is ``None`` when ``backup=False``. Because the method is
          atomic, if it is present and non-None the transaction has committed
          successfully and the ID is a valid database row.
        """
        graph = version.graph
        Graph.increment_version_if_current(pk=graph.pk, expected=expected_save_version)

        prepared = self._prepare(version)
        warnings = list(prepared.filter_warnings)

        auto_backup_id = None
        if backup:
            backup_version = self.save_version(
                graph=graph,
                name=f"Before restore to '{version.name}'",
                description=f"Auto-backup created before restoring version #{version.id}",
            )
            auto_backup_id = backup_version.id

        node_mapper = self._manager.apply_snapshot_to_graph(
            graph, prepared.filtered_snapshot, prepared.available_dependencies
        )

        warnings.extend(
            self._manager.restore_secret_declarations(
                graph=graph,
                declarations=prepared.converted_snapshot.get("secret_declarations"),
                node_mapper=node_mapper,
            )
        )

        self._manager.change_old_warnings_ids(warnings, node_mapper)

        return {
            "restored": True,
            "graph_id": graph.id,
            "warnings": warnings,
            "auto_backup_version_id": auto_backup_id,
        }

    def _prepare(self, version: GraphVersion) -> PreparedVersion:
        converted_snapshot = self._manager.convert_snapshot_to_current_version(version.snapshot)
        dependencies_validation = self._manager.validate_dependencies(version.dependencies or {})
        filtered_snapshot, filter_warnings = self._manager.filter_snapshot(
            converted_snapshot, dependencies_validation["missing"]
        )
        return PreparedVersion(
            converted_snapshot=converted_snapshot,
            filtered_snapshot=filtered_snapshot,
            available_dependencies=dependencies_validation["available"],
            filter_warnings=tuple(filter_warnings),
        )
