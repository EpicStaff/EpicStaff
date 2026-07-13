from django.db import transaction

from tables.graph_versioning.manager import GraphVersioningManager
from tables.import_export.constants import IMPORT_VERSION
from tables.models import (
    GraphVersion,
    Graph,
)


class GraphVersioningService:
    def __init__(self):
        self._manager = GraphVersioningManager()

    @transaction.atomic
    def save_version(
        self, graph: Graph, name: str, description: str = ""
    ) -> GraphVersion:
        """
        Create a named version snapshot of the given graph.
        """
        snapshot = self._manager.create_snapshot(graph)
        snapshot["version"] = IMPORT_VERSION
        light_deps = self._manager.collect_dependencies(graph)

        return GraphVersion.objects.create(
            graph=graph,
            name=name,
            description=description,
            snapshot=snapshot,
            dependencies=light_deps,
        )

    @transaction.atomic
    def create_graph_from_version(self, version: GraphVersion) -> dict:
        """
        Create a brand-new Graph from a version snapshot.
        The new graph is fully independent — own id/uuid, zero GraphVersion rows.
        """
        source_graph = version.graph
        deps = version.dependencies or {}

        snapshot = self._manager.convert_snapshot_to_current_version(version.snapshot)
        deps_validation = self._manager.validate_dependencies(deps)
        filtered_snapshot, warnings = self._manager.filter_snapshot(
            snapshot, deps_validation["missing"]
        )

        graph_name = snapshot.get("name", "Flow")
        new_graph, node_mapper = self._manager.create_graph_from_snapshot(
            filtered_snapshot,
            deps_validation["available"],
            graph_name=graph_name,
            version_name=version.name,
            org_id=source_graph.org_id,
        )

        # Copy labels from source graph
        new_graph.labels.set(source_graph.labels.all())

        self._manager.change_old_warnings_ids(warnings, node_mapper)

        return {
            "created": True,
            "graph_id": new_graph.id,
            "warnings": warnings,
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

        deps = version.dependencies or {}

        snapshot = self._manager.convert_snapshot_to_current_version(version.snapshot)

        deps_validation = self._manager.validate_dependencies(deps)
        filtered_snapshot, warnings = self._manager.filter_snapshot(
            snapshot, deps_validation["missing"]
        )

        auto_backup_id = None
        if backup:
            backup_version = self.save_version(
                graph=graph,
                name=f"Before restore to '{version.name}'",
                description=f"Auto-backup created before restoring version #{version.id}",
            )
            auto_backup_id = backup_version.id

        node_mapper = self._manager.apply_snapshot_to_graph(
            graph, filtered_snapshot, deps_validation["available"]
        )

        self._manager.change_old_warnings_ids(warnings, node_mapper)

        return {
            "restored": True,
            "graph_id": graph.id,
            "warnings": warnings,
            "auto_backup_version_id": auto_backup_id,
        }
