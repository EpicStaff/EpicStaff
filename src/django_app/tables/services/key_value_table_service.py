import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import connection, transaction
from django.db.models import Count, QuerySet, TextField, Value
from django.db.models.functions import Cast, Coalesce, Collate, Left, Length
from django.db.models.lookups import GreaterThan
from rbac.access.resolver import PermissionResolver
from rbac.exceptions import OrgMembershipRequiredError
from rbac.models.enums import Permission, ResourceType
from tables.constants.key_value_constants import MAX_VALUE_BYTES, VALUE_PREVIEW_CHARS
from tables.exceptions import (
    KeyValueEntryKeyInvalidError,
    KeyValueEntryValueTooLargeError,
    KeyValueModeDeniedError,
    KeyValueTableNotFoundError,
)
from tables.models import (
    KeyValueNode,
    KeyValueTable,
    KeyValueTableEntry,
    Session,
    SubGraphNode,
)
from tables.validators.key_value_entries_validator import resolved_key_error

# The one order in which entry rows are locked, by every statement that locks several at
# once: two such statements locking overlapping keys in different orders can deadlock.
# Keys are ASCII identifiers (KEY_PATTERN), so Python's code-point order is the same as
# "C" collation byte order.
_ENTRY_LOCK_ORDER = Collate("key", "C")


# Every permission a node of that mode needs on its table. Checked one by one:
# EffectivePermissions.can() passes when any bit of a combined flag is held. Delete needs
# READ too: its session message reports the values it deleted.
MODE_PERMISSIONS = {
    KeyValueNode.Mode.READ: (Permission.READ,),
    KeyValueNode.Mode.WRITE: (Permission.CREATE, Permission.UPDATE),
    KeyValueNode.Mode.DELETE: (Permission.READ, Permission.DELETE),
}


def _value_text() -> Cast:
    return Cast("value", TextField())


def _value_preview() -> Left:
    return Left(_value_text(), VALUE_PREVIEW_CHARS)


@dataclass(frozen=True)
class EntryLookup:
    exists: bool
    value_preview: str | None
    updated_at: datetime | None


class KeyValueTableService:
    """Owns every rule about key-value tables and their entries."""

    def read(self, table: KeyValueTable, keys: list[str]) -> dict[str, Any]:
        for key in keys:
            self.validate_key(key)
        return dict(
            KeyValueTableEntry.objects.filter(table=table, key__in=keys).values_list("key", "value")
        )

    def write(
        self,
        table: KeyValueTable,
        entries: dict[str, Any],
        session: Session | None = None,
    ) -> list[str]:
        """Upsert `entries` into `table` and return the keys that did not exist before, sorted.

        Raises:
            KeyValueTableNotFoundError (404): the table was deleted meanwhile.
        """
        for key, value in entries.items():
            self.validate_key(key)
            self.validate_value(value)
        with transaction.atomic():
            self._lock_table_for_entry_writes(table)
            # NOTE: created flags are approximate under concurrent writers; use RETURNING
            # (xmax = 0) via raw SQL if exact created flags ever matter.
            existing = set(
                KeyValueTableEntry.objects.filter(table=table, key__in=entries).values_list(
                    "key", flat=True
                )
            )
            # Postgres locks an upsert's conflicting rows in VALUES order, so the rows go in
            # _ENTRY_LOCK_ORDER.
            rows = [
                KeyValueTableEntry(
                    table=table, key=key, value=entries[key], updated_by_session=session
                )
                for key in sorted(entries)
            ]
            KeyValueTableEntry.objects.bulk_create(
                rows,
                update_conflicts=True,
                unique_fields=["table", "key"],
                update_fields=["value", "updated_at", "updated_by_session"],
            )
        return sorted(set(entries) - existing)

    def _lock_table_for_entry_writes(self, table: KeyValueTable) -> None:
        # Without this the lock order is entries -> table: the upsert locks existing entry
        # rows, then the deferred FK check of its new rows takes FOR KEY SHARE on the table
        # row at commit. delete_table goes table -> entries (FOR UPDATE, then the cascade
        # deletes the entries), so the two would deadlock. Taking FOR KEY SHARE up front
        # makes both sides go table -> entries.
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT 1 FROM {connection.ops.quote_name(KeyValueTable._meta.db_table)} "
                "WHERE id = %s FOR KEY SHARE",
                [table.pk],
            )
            if cursor.fetchone() is None:
                raise KeyValueTableNotFoundError(table.pk)

    def delete(self, table: KeyValueTable, keys: list[str]) -> dict[str, Any]:
        """Delete the entries stored under `keys` in `table` and return their values by key.

        Keys with no entry are absent from the result. The rows are locked, read and deleted
        by primary key in one transaction, so a concurrent write cannot change a value between
        reading it and deleting it: every returned value is exactly the one deleted.

        Raises:
            KeyValueEntryKeyInvalidError (400): a key breaks KEY_PATTERN or MAX_KEY_LENGTH;
                nothing is deleted.
        """
        for key in keys:
            self.validate_key(key)
        with transaction.atomic():
            rows = list(
                KeyValueTableEntry.objects.select_for_update()
                .filter(table=table, key__in=keys)
                .order_by(_ENTRY_LOCK_ORDER)
                .values_list("pk", "key", "value")
            )
            if rows:
                KeyValueTableEntry.objects.filter(pk__in=[pk for pk, _, _ in rows]).delete()
        return {key: value for _, key, value in rows}

    def lookup(self, table: KeyValueTable, keys: list[str]) -> dict[str, EntryLookup]:
        # Preview is computed in the database (truncated jsonb-as-text) so a lookup of up
        # to MAX_KEYS_PER_REQUEST keys never pulls full values into Python.
        found = {
            row["key"]: row
            for row in KeyValueTableEntry.objects.filter(table=table, key__in=keys)
            .annotate(preview=_value_preview())
            .values("key", "preview", "updated_at")
        }
        return {
            key: (
                EntryLookup(True, found[key]["preview"], found[key]["updated_at"])
                if key in found
                else EntryLookup(False, None, None)
            )
            for key in keys
        }

    def with_value_preview(
        self, entries: QuerySet[KeyValueTableEntry]
    ) -> QuerySet[KeyValueTableEntry]:
        """Replace each entry's full `value` with `value_preview` and `value_truncated`.

        Both are computed in the database and `value` is deferred, so a page of entries
        never pulls values of up to MAX_VALUE_BYTES each into Python. The preview is the
        first VALUE_PREVIEW_CHARS characters of the value's jsonb text; a NULL value
        previews as "null", its JSON text.

        Apply it to one page's rows (e.g. `pk__in` page ids), not to a sorted, limited
        query: Postgres computes these cheap expressions below the Sort, for every row.
        """
        # NOTE: Postgres does not share the cast between the two expressions, so each row's
        # value is rendered as text twice. Both stay inside the database.
        return entries.defer("value").annotate(
            value_preview=Coalesce(_value_preview(), Value("null")),
            value_truncated=Coalesce(
                GreaterThan(Length(_value_text()), VALUE_PREVIEW_CHARS), Value(False)
            ),
        )

    def assert_can_configure(self, user, table: KeyValueTable, mode: str) -> None:
        """Assert `user` holds every key_value_tables permission a `mode` node needs on `table`.

        Raises:
            KeyValueModeDeniedError (403): the user's role lacks one of MODE_PERMISSIONS[mode].
            OrgMembershipRequiredError (403): the user is not a member of the table's org.
        """
        # Resolved once for all the mode's permissions; the resolver applies the superadmin
        # bypass and raises OrgMembershipRequiredError, as assert_org_permission would.
        effective = PermissionResolver().resolve(user=user, org_id=table.org_id)
        if not all(
            effective.can(ResourceType.KEY_VALUE_TABLES, permission)
            for permission in MODE_PERMISSIONS[mode]
        ):
            raise KeyValueModeDeniedError(mode, table.name)

    def can_configure(self, user, table: KeyValueTable, mode: str) -> bool:
        try:
            self.assert_can_configure(user, table, mode)
        except (KeyValueModeDeniedError, OrgMembershipRequiredError):
            return False
        return True

    def delete_table(self, table: KeyValueTable) -> None:
        """Delete `table` with its entries and unlink every Key-Value node that used it.

        Nodes keep existing with `key_value_table = NULL` (the FK's SET_NULL, which Django
        applies through the base manager, so nodes of soft-deleted flows are unlinked too).

        Raises:
            KeyValueTableNotFoundError (404): the table was deleted meanwhile, e.g. by a
                concurrent request this one waited on for the row lock.
        """
        # Row lock first. Two kinds of writers take FOR KEY SHARE on this row and so wait for
        # this delete: a node save referencing the table, at its FK check (it then fails
        # the FK instead of linking a node after SET_NULL ran and failing this delete at
        # commit), and a runtime entry write, before it locks any entry (see
        # _lock_table_for_entry_writes), so the lock order is table -> entries on both sides.
        with transaction.atomic():
            if KeyValueTable.objects.select_for_update().filter(pk=table.pk).first() is None:
                raise KeyValueTableNotFoundError(table.pk)
            table.delete()

    def usage(self, table: KeyValueTable) -> dict[str, int]:
        """Count the Key-Value nodes using `table` and their distinct flows.

        Only live nodes of flows that are not soft-deleted count: deleting the table unlinks
        soft-deleted ones too, but nobody sees them.
        """
        return KeyValueNode.objects.filter(
            key_value_table=table, graph__is_soft_deleted=False
        ).aggregate(node_count=Count("pk"), flow_count=Count("graph_id", distinct=True))

    def session_can_access(self, session: Session, table: KeyValueTable) -> bool:
        """Access is granted by saved configuration, never by the runtime caller.

        v1 source: a KeyValueNode referencing the table in the session's graph or in any
        subgraph it reaches (crew runs subgraph nodes under the parent session id).
        """
        return KeyValueNode.objects.filter(
            graph_id__in=self._session_graph_ids(session), key_value_table=table
        ).exists()

    def find_by_name(self, org_id: int, name: str) -> KeyValueTable | None:
        return KeyValueTable.objects.filter(org_id=org_id, name__iexact=name).first()

    def resolve_reference(
        self,
        org_id: int,
        table_id: int | None,
        table_name: str | None,
        mode: str,
        user=None,
    ) -> KeyValueTable | None:
        """Re-bind a copied, imported or restored node's table reference inside `org_id`.

        The table with `table_id` wins only if it is in `org_id` and still carries
        `table_name`; otherwise any table of `org_id` with that name; otherwise `None`.
        A table id alone is never trusted, so a foreign-org id is never kept, and
        nothing is created.

        Args:
            mode: The node's mode, which decides the permissions `user` needs.
            user: The acting user. When given, the table is bound only if they hold
                every permission in MODE_PERMISSIONS[mode] in `org_id`; otherwise `None`,
                so the node shows "No table" instead of failing the whole operation.
                `None` means the caller has no acting user and skips the check.
        """
        table = self._find_reference(org_id, table_id, table_name)
        if table is None or user is None or self.can_configure(user, table, mode):
            return table
        return None

    def _find_reference(
        self, org_id: int, table_id: int | None, table_name: str | None
    ) -> KeyValueTable | None:
        if not table_name:
            return None
        if table_id is not None:
            same_table = KeyValueTable.objects.filter(
                pk=table_id, org_id=org_id, name__iexact=table_name
            ).first()
            if same_table is not None:
                return same_table
        return self.find_by_name(org_id, table_name)

    def validate_key(self, key: str) -> None:
        """Reject a resolved key that could not have come from a valid node.

        Raises:
            KeyValueEntryKeyInvalidError (400): the key breaks KEY_PATTERN or MAX_KEY_LENGTH.
        """
        error = resolved_key_error(key)
        if error:
            raise KeyValueEntryKeyInvalidError(key, error)

    def validate_value(self, value: Any) -> None:
        size_bytes = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        if size_bytes > MAX_VALUE_BYTES:
            raise KeyValueEntryValueTooLargeError(size_bytes, MAX_VALUE_BYTES)

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
