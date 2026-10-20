from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from helpers.logger import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.shared.retention import (
    FINAL_SESSION_CALLBACK_STATUSES,
    SESSION_CHILD_TABLES,
    SESSION_PARENT_COLUMN,
    SESSION_SET_NULL_COLUMNS,
    TERMINAL_SESSION_STATUSES,
)

_LIST_ORG_RETENTION = text(
    """
    SELECT organization.id AS org_id, retention.sessions_days, retention.conversations_days
    FROM rbac_organization organization
    LEFT JOIN rbac_organization_retention retention ON retention.org_id = organization.id
    ORDER BY organization.id
    """
)

# Root sessions only: subflow sessions go with their root. FOR UPDATE because the rows are
# deleted; SKIP LOCKED leaves a root Django is still writing (its status, token total or
# subflow sessions, all under a row lock) for the next night instead of waiting on it.
# Postgres re-evaluates the status and finished_at conditions on the locked row version.
_PICK_ROOTS = """
    SELECT session.id
    FROM tables_session session
    WHERE session.{parent_column} IS NULL
      AND session.status = ANY(:terminal_statuses)
      AND session.finished_at < :cutoff
      AND NOT (session.id = ANY(:held_root_ids))
      AND {org_condition}
    ORDER BY session.id
    LIMIT :batch_size
    FOR UPDATE OF session SKIP LOCKED
"""
# Sessions of a flow in the recycle bin are left alone: purging the bin deletes them through
# Django's cascade, which locks them in its own order, and the two must not meet.
_ORG_CONDITION = (
    "EXISTS (SELECT 1 FROM tables_graph graph WHERE graph.id = session.graph_id "
    "AND graph.org_id = :org_id AND graph.soft_deleted_at IS NULL)"
)
# tables_graph.org_id is NOT NULL, so a session belongs to no organization only when it has
# no flow; deleting a flow deletes its sessions, so graph_id is NULL only for sessions
# created without one.
_NO_ORG_CONDITION = "session.graph_id IS NULL"

_EXPAND_TREE = text(
    f"""
    WITH RECURSIVE tree (id, root_id) AS (
        SELECT id, id FROM tables_session WHERE id = ANY(:root_ids)
        UNION ALL
        SELECT child.id, tree.root_id
        FROM tables_session child
        JOIN tree ON child.{SESSION_PARENT_COLUMN} = tree.id
    )
    SELECT id, root_id FROM tree
    """
)

_LOCK_SESSIONS = text(
    "SELECT id FROM tables_session WHERE id = ANY(:session_ids) FOR UPDATE SKIP LOCKED"
)

# Re-checked across the whole locked tree: a callback still owed on any session keeps it.
_ROOTS_WITH_OWED_CALLBACKS = text(
    """
    SELECT DISTINCT tree.root_id
    FROM unnest(CAST(:session_ids AS bigint[]), CAST(:root_ids AS bigint[])) AS tree (id, root_id)
    JOIN tables_sessioncallback callback ON callback.session_id = tree.id
    WHERE NOT (callback.status = ANY(:final_statuses))
    """
)

_CLEAR_SET_NULL_COLUMNS = tuple(
    text(f"UPDATE {link.table} SET {link.column} = NULL WHERE {link.column} = ANY(:session_ids)")
    for link in SESSION_SET_NULL_COLUMNS
)
_DELETE_CHILD_ROWS = tuple(
    text(f"DELETE FROM {link.table} WHERE {link.column} = ANY(:session_ids)")
    for link in SESSION_CHILD_TABLES
)
_DELETE_SESSIONS = text("DELETE FROM tables_session WHERE id = ANY(:session_ids)")


@dataclass(frozen=True)
class OrgRetentionRow:
    """An organization's own retention choices; None inherits the instance default."""

    org_id: int
    sessions_days: int | None
    conversations_days: int | None


class RetentionInterruptedError(Exception):
    """A purge failed after some batches may already have been committed.

    The failure is chained as ``__cause__``.

    Attributes:
        deleted: Sessions deleted, and committed, before the failure.
    """

    def __init__(self, deleted: int):
        super().__init__(f"failed after deleting {deleted} session(s)")
        self.deleted = deleted


@dataclass(frozen=True)
class _BatchResult:
    picked_roots: int
    deleted_sessions: int
    held_root_ids: frozenset[int]


class RetentionRepository:
    """Raw-SQL deletion of expired sessions for the nightly retention job.

    The database's foreign keys do not cascade (Django emulates on_delete in Python), so the
    whole session tree is deleted explicitly, following the contract in
    ``src.shared.retention``. Nothing here touches storage objects, Redis or audit events.

    Args:
        session_factory: Makes the AsyncSession each batch runs in.
        lock_timeout_ms: Longest a batch waits for a row lock held elsewhere (a row the
            delete or the SET NULL update must touch) before it gives up; the rows are
            retried on the next run instead of queueing behind Django.
    """

    def __init__(self, session_factory: Callable[[], AsyncSession], lock_timeout_ms: int = 5000):
        self.session_factory = session_factory
        self.lock_timeout_ms = lock_timeout_ms

    async def list_org_retention(self) -> list[OrgRetentionRow]:
        """Return every organization with its retention choices, None where it chose nothing."""
        async with self.session_factory() as session:
            result = await session.execute(_LIST_ORG_RETENTION)
            return [
                OrgRetentionRow(row.org_id, row.sessions_days, row.conversations_days)
                for row in result
            ]

    async def delete_expired_sessions(
        self, org_id: int | None, cutoff: datetime, batch_size: int = 200
    ) -> int:
        """Delete finished root sessions older than ``cutoff`` with their subflow sessions.

        A root qualifies when its status is terminal, it finished strictly before ``cutoff``,
        its flow is not in the recycle bin and no session in its tree still owes a callback.
        Each batch is its own transaction: the roots are locked (skipping any another
        transaction holds), their trees expanded and locked, SET_NULL references cleared,
        child rows and then the sessions deleted. Stops after the first batch that picks fewer
        than ``batch_size`` roots. Every committed batch that picked roots is logged at once
        (organization, cutoff, counts), so deleted data leaves a trace even if the process
        dies before the purge returns.

        Args:
            org_id: The organization whose sessions expire, or None for sessions without a flow.
            cutoff: Aware datetime; sessions that finished before it are deleted.

        Returns:
            Session rows deleted, subflow sessions included.

        Raises:
            RetentionInterruptedError: A batch failed, including on a lock timeout; carries
                what earlier batches deleted and chains the failure.
        """
        pick_roots = text(
            _PICK_ROOTS.format(
                parent_column=SESSION_PARENT_COLUMN,
                org_condition=_NO_ORG_CONDITION if org_id is None else _ORG_CONDITION,
            )
        )
        deleted = 0
        held_root_ids: set[int] = set()
        while True:
            try:
                batch = await self._delete_batch(
                    pick_roots, org_id, cutoff, batch_size, held_root_ids
                )
            except Exception as error:
                raise RetentionInterruptedError(deleted) from error
            deleted += batch.deleted_sessions
            # Roots kept back stay out of later picks, or a full batch of them would repeat forever.
            held_root_ids |= batch.held_root_ids
            if batch.picked_roots < batch_size:
                return deleted

    async def _delete_batch(
        self,
        pick_roots,
        org_id: int | None,
        cutoff: datetime,
        batch_size: int,
        held_root_ids: set[int],
    ) -> _BatchResult:
        async with self.session_factory() as session:
            async with session.begin():
                # SET LOCAL takes no bind parameters; the value is an int from our own code.
                await session.execute(text(f"SET LOCAL lock_timeout = {int(self.lock_timeout_ms)}"))
                root_ids = list(
                    (
                        await session.execute(
                            pick_roots,
                            {
                                "terminal_statuses": sorted(TERMINAL_SESSION_STATUSES),
                                "cutoff": cutoff,
                                "held_root_ids": sorted(held_root_ids),
                                "org_id": org_id,
                                "batch_size": batch_size,
                            },
                        )
                    ).scalars()
                )
                if not root_ids:
                    return _BatchResult(0, 0, frozenset())

                tree, held = await self._lock_trees(session, root_ids)
                session_ids = [row.id for row in tree if row.root_id not in held]
                deleted_sessions = 0
                if session_ids:
                    parameters = {"session_ids": session_ids}
                    for statement in (*_CLEAR_SET_NULL_COLUMNS, *_DELETE_CHILD_ROWS):
                        await session.execute(statement, parameters)
                    result = await session.execute(_DELETE_SESSIONS, parameters)
                    deleted_sessions = result.rowcount
            # Logged as soon as the batch is committed, with no await in between: the service's
            # per-organization summary never runs if the process is cancelled or killed later.
            logger.info(
                "Retention sessions batch committed: org={} cutoff={} roots_picked={} "
                "sessions_deleted={}",
                "no flow" if org_id is None else org_id,
                cutoff.isoformat(),
                len(root_ids),
                deleted_sessions,
            )
            return _BatchResult(len(root_ids), deleted_sessions, frozenset(held))

    async def _lock_trees(self, session: AsyncSession, root_ids: list[int]):
        """Lock the descendants of the locked roots; return the tree and the roots to keep.

        A root is kept when one of its sessions is locked elsewhere, or still owes a callback.
        The tree is expanded again after locking: a subflow session committed between the
        first expansion and the lock would otherwise be left out of the delete.
        """
        tree = (await session.execute(_EXPAND_TREE, {"root_ids": root_ids})).all()
        descendant_ids = [row.id for row in tree if row.id != row.root_id]
        locked: set[int] = set()
        if descendant_ids:
            locked = set(
                (await session.execute(_LOCK_SESSIONS, {"session_ids": descendant_ids})).scalars()
            )
            tree = (await session.execute(_EXPAND_TREE, {"root_ids": root_ids})).all()
        held = {row.root_id for row in tree if row.id != row.root_id and row.id not in locked}
        owed = await session.execute(
            _ROOTS_WITH_OWED_CALLBACKS,
            {
                "session_ids": [row.id for row in tree],
                "root_ids": [row.root_id for row in tree],
                "final_statuses": sorted(FINAL_SESSION_CALLBACK_STATUSES),
            },
        )
        held |= set(owed.scalars())
        return tree, held
