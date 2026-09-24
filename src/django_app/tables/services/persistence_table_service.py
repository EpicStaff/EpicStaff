import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rbac.access.asserts import assert_org_permission
from rbac.models.enums import Permission, ResourceType
from tables.constants.persistence_constants import (
    MAX_KEY_LENGTH,
    MAX_VALUE_BYTES,
    VALUE_PREVIEW_CHARS,
)
from tables.exceptions import (
    PersistenceKeyInvalidError,
    PersistenceTableInUseError,
    PersistenceValueTooLargeError,
)
from tables.models import (
    PersistenceNode,
    PersistenceTable,
    PersistenceTableEntry,
    Session,
    SubGraphNode,
)


@dataclass(frozen=True)
class EntryLookup:
    exists: bool
    value_preview: str | None
    updated_at: datetime | None


class PersistenceTableService:
    """Owns every rule about persistence tables and their entries."""

    def read(self, table: PersistenceTable, keys: list[str]) -> dict[str, Any]:
        return dict(
            PersistenceTableEntry.objects.filter(table=table, key__in=keys).values_list(
                "key", "value"
            )
        )

    def write(
        self,
        table: PersistenceTable,
        entries: dict[str, Any],
        session: Session | None = None,
    ) -> int:
        for key, value in entries.items():
            self.validate_key(key)
            self.validate_value(value)
        rows = [
            PersistenceTableEntry(table=table, key=key, value=value, updated_by_session=session)
            for key, value in entries.items()
        ]
        PersistenceTableEntry.objects.bulk_create(
            rows,
            update_conflicts=True,
            unique_fields=["table", "key"],
            update_fields=["value", "updated_at", "updated_by_session"],
        )
        return len(rows)

    def delete(self, table: PersistenceTable, keys: list[str]) -> int:
        deleted, _ = PersistenceTableEntry.objects.filter(table=table, key__in=keys).delete()
        return deleted

    def lookup(self, table: PersistenceTable, keys: list[str]) -> dict[str, EntryLookup]:
        found = {
            entry.key: entry
            for entry in PersistenceTableEntry.objects.filter(table=table, key__in=keys)
        }
        return {
            key: (
                EntryLookup(True, self._preview(found[key].value), found[key].updated_at)
                if key in found
                else EntryLookup(False, None, None)
            )
            for key in keys
        }

    def assert_can_use(self, user, table: PersistenceTable) -> None:
        """Raise PermissionDenied (403) unless `user` holds persistent_data:USE in the table's org."""
        assert_org_permission(
            user=user,
            org_id=table.org_id,
            resource_type=ResourceType.PERSISTENT_DATA,
            action=Permission.USE,
        )

    def assert_not_in_use(self, table: PersistenceTable) -> None:
        flow_names = list(
            PersistenceNode.objects.filter(persistence_table=table, graph__is_soft_deleted=False)
            .values_list("graph__name", flat=True)
            .distinct()
            .order_by("graph__name")
        )
        if flow_names:
            raise PersistenceTableInUseError(flow_names)

    def session_can_access(self, session: Session, table: PersistenceTable) -> bool:
        """Access is granted by saved configuration, never by the runtime caller.

        v1 source: a PersistenceNode referencing the table in the session's graph or in any
        subgraph it reaches (crew runs subgraph nodes under the parent session id).
        """
        return PersistenceNode.objects.filter(
            graph_id__in=self._session_graph_ids(session), persistence_table=table
        ).exists()

    def validate_key(self, key: str) -> None:
        if not key or len(key) > MAX_KEY_LENGTH:
            raise PersistenceKeyInvalidError(key, MAX_KEY_LENGTH)

    def validate_value(self, value: Any) -> None:
        size_bytes = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        if size_bytes > MAX_VALUE_BYTES:
            raise PersistenceValueTooLargeError(size_bytes, MAX_VALUE_BYTES)

    def _preview(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)[:VALUE_PREVIEW_CHARS]

    def _session_graph_ids(self, session: Session) -> set[int]:
        graph_ids = {session.graph_id}
        frontier = {session.graph_id}
        while frontier:
            children = set(
                SubGraphNode.objects.filter(
                    graph_id__in=frontier, subgraph_id__isnull=False
                ).values_list("subgraph_id", flat=True)
            )
            frontier = children - graph_ids
            graph_ids |= frontier
        return graph_ids
