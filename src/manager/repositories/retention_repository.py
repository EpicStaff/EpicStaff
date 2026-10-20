from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

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

# The organization's flows, listed once per run. Flows in the recycle bin are left alone:
# purging the bin deletes their sessions through Django's cascade, which locks them in its
# own order, and the two must not meet.
_LIST_ORG_GRAPHS = text(
    """
    SELECT graph.id
    FROM tables_graph graph
    WHERE graph.org_id = :org_id AND graph.soft_deleted_at IS NULL
    ORDER BY graph.id
    """
)

# Root sessions only: subflow sessions go with their root. FOR UPDATE because the rows are
# deleted; SKIP LOCKED leaves a root Django is still writing (its status, token total or
# subflow sessions, all under a row lock) for the next night instead of waiting on it.
# Postgres re-evaluates the status and finished_at conditions on the locked row version.
#
# One flow at a time, keyset-paged oldest first: each batch starts after the last
# (finished_at, id) the previous one picked, so roots already deleted, held back or skipped
# are never scanned again in the same run. With graph_id fixed, the batch is one range of
# the session_root_graph_finished index (graph_id, finished_at, id), starting at the cursor
# and already in ORDER BY order, so it stops after batch_size rows without a sort; ordering
# across several flows would sort every remaining root of the organization on every batch.
# graph_id leads the ORDER BY although it is constant in a pick: Postgres drops it from the
# required order for graph_id = :graph_id but not for graph_id IS NULL, and without it the
# no-flow pick would sort every remaining flowless root.
_PICK_ROOTS = """
    SELECT session.id, session.finished_at
    FROM tables_session session
    WHERE {scope_condition}
      AND session.{parent_column} IS NULL
      AND session.status = ANY(:terminal_statuses)
      AND session.finished_at < :cutoff
      AND (session.finished_at, session.id) > (:after_finished_at, :after_id)
    ORDER BY session.graph_id, session.finished_at, session.id
    LIMIT :batch_size
    FOR UPDATE OF session SKIP LOCKED
"""
# Before any real finished_at, so each flow starts at its oldest root.
_CURSOR_START = (datetime(1, 1, 1, tzinfo=UTC), 0)
# Re-checks the flow on every batch, so one moved to the recycle bin mid-run is left alone
# from then on. The org check in it is defence in depth: the scoping itself comes from the
# org-filtered flow list plus session.graph_id = :graph_id. Uncorrelated with the session
# row, so Postgres evaluates it once per batch and the index range scan is unchanged.
_GRAPH_SCOPE_CONDITION = (
    "session.graph_id = :graph_id AND EXISTS (SELECT 1 FROM tables_graph graph "
    "WHERE graph.id = :graph_id AND graph.org_id = :org_id AND graph.soft_deleted_at IS NULL)"
)
# tables_graph.org_id is NOT NULL, so a session belongs to no organization only when it has
# no flow; deleting a flow deletes its sessions, so graph_id is NULL only for sessions
# created without one.
_NO_FLOW_SCOPE_CONDITION = "session.graph_id IS NULL"
_PICK_FLOW_ROOTS = text(
    _PICK_ROOTS.format(scope_condition=_GRAPH_SCOPE_CONDITION, parent_column=SESSION_PARENT_COLUMN)
)
_PICK_NO_FLOW_ROOTS = text(
    _PICK_ROOTS.format(
        scope_condition=_NO_FLOW_SCOPE_CONDITION, parent_column=SESSION_PARENT_COLUMN
    )
)

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
    # The (finished_at, id) of the newest root picked; the next batch starts after it.
    cursor: tuple[datetime, int]


class RetentionRepository:
    """Raw-SQL deletion of expired sessions for the nightly retention job.

    The database's foreign keys do not cascade (Django emulates on_delete in Python), so the
    whole session tree is deleted explicitly, following the contract in
    ``src.shared.retention``. Nothing here touches storage objects, Redis or audit events.

    Args:
        session_factory: Makes the AsyncSession each batch runs in.
        lock_timeout_ms: Longest the flow listing or a batch waits for a lock held elsewhere
            (on tables_graph, or a row the delete or the SET NULL update must touch) before
            it gives up; the rows are retried on the next run instead of queueing behind
            Django.
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
        The organization's flows are listed once and purged one after another, in id order;
        within a flow, roots are taken oldest first (by finished_at, then id). There is no
        order across flows, so a run that stops partway leaves some flows fully purged and
        others untouched; retention correctness does not depend on the order, the next run
        picks up whatever is still due. A flow moved to the recycle bin during the run is
        skipped from its next batch on.

        Each batch is its own transaction: the roots are locked (skipping any another
        transaction holds), their trees expanded and locked, SET_NULL references cleared,
        child rows and then the sessions deleted. The next batch of the flow starts after the
        newest root this one picked, so a root the run has passed is not retried in the same
        run, and waits for the next night: one held back (a session in its tree locked
        elsewhere, or a callback owed) or skipped because another transaction had it locked.
        A flow is done after its first batch that picks fewer than ``batch_size`` roots.
        Every committed batch that picked roots is logged at once (organization, flow,
        cutoff, counts), so deleted data leaves a trace even if the process dies before the
        purge returns.

        Args:
            org_id: The organization whose sessions expire, or None for sessions without a
                flow, which are purged as a single range.
            cutoff: Aware datetime; sessions that finished before it are deleted.

        Returns:
            Session rows deleted, subflow sessions included, across all flows.

        Raises:
            RetentionInterruptedError: Listing the flows or a batch failed, including on a
                lock timeout; carries what earlier batches, of any flow, deleted and chains
                the failure.
        """
        deleted = 0
        try:
            graph_ids = [None] if org_id is None else await self._list_org_graphs(org_id)
        except Exception as error:
            raise RetentionInterruptedError(deleted) from error
        for graph_id in graph_ids:
            cursor = _CURSOR_START
            while True:
                try:
                    batch = await self._delete_batch(org_id, graph_id, cutoff, batch_size, cursor)
                except Exception as error:
                    raise RetentionInterruptedError(deleted) from error
                deleted += batch.deleted_sessions
                # The cursor passes held roots too, or a full batch of them would repeat forever.
                cursor = batch.cursor
                if batch.picked_roots < batch_size:
                    break
        return deleted

    async def _list_org_graphs(self, org_id: int) -> list[int]:
        async with self.session_factory() as session, session.begin():
            # Bounded like a batch: a lock held on tables_graph fails the run, not stalls it.
            await self._set_lock_timeout(session)
            result = await session.execute(_LIST_ORG_GRAPHS, {"org_id": org_id})
            return list(result.scalars())

    async def _set_lock_timeout(self, session: AsyncSession) -> None:
        # SET LOCAL takes no bind parameters; the value is an int from our own code.
        await session.execute(text(f"SET LOCAL lock_timeout = {int(self.lock_timeout_ms)}"))

    async def _delete_batch(
        self,
        org_id: int | None,
        graph_id: int | None,
        cutoff: datetime,
        batch_size: int,
        cursor: tuple[datetime, int],
    ) -> _BatchResult:
        pick_roots = _PICK_NO_FLOW_ROOTS if graph_id is None else _PICK_FLOW_ROOTS
        async with self.session_factory() as session:
            async with session.begin():
                await self._set_lock_timeout(session)
                after_finished_at, after_id = cursor
                picked = (
                    await session.execute(
                        pick_roots,
                        {
                            "terminal_statuses": sorted(TERMINAL_SESSION_STATUSES),
                            "cutoff": cutoff,
                            "after_finished_at": after_finished_at,
                            "after_id": after_id,
                            "org_id": org_id,
                            "graph_id": graph_id,
                            "batch_size": batch_size,
                        },
                    )
                ).all()
                if not picked:
                    return _BatchResult(0, 0, cursor)
                root_ids = [row.id for row in picked]
                # Rows come back in (finished_at, id) order, and finished_at is never changed
                # once set, so the last row is the newest picked.
                next_cursor = (picked[-1].finished_at, picked[-1].id)

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
                "Retention sessions batch committed: org={} graph={} cutoff={} roots_picked={} "
                "sessions_deleted={}",
                "no flow" if org_id is None else org_id,
                "none" if graph_id is None else graph_id,
                cutoff.isoformat(),
                len(root_ids),
                deleted_sessions,
            )
            return _BatchResult(len(root_ids), deleted_sessions, next_cursor)

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
