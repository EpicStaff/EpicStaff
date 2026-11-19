"""Reading the sessions of a session export a chunk at a time.

An export may carry thousands of sessions with every message, so nothing here holds
more than one chunk of sessions and one session's messages at once, and the number of
queries grows with the number of chunks, not of sessions.
"""

from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import batched

from django.db.models import Case, IntegerField, QuerySet, Value, When

from tables.import_export.strategies.session import SessionStrategy
from tables.models.session_models import Session

# Sessions loaded per query; their messages are read in one query per chunk.
SESSION_CHUNK_SIZE = 100
# Message rows fetched per round trip of the messages query's server-side cursor.
MESSAGE_FETCH_SIZE = 500
# Most ids one sub-session lookup sends in its IN list.
SUB_SESSION_LOOKUP_BATCH = 5000


@dataclass(frozen=True)
class ExportedSessions:
    """The sessions one export carries: the requested ones and every sub-session below them."""

    # Each session after its sub-sessions, the trees in the order they were requested:
    # the order `ExportService` collects them in, and so the order of `sessions.json`.
    depth_first_ids: list[int]
    # The topmost exported ancestor of each session (itself when its parent is not
    # exported). A subflow's copied messages only ever repeat rows of its own tree.
    tree_of: dict[int, int]

    @property
    def ids_by_session_id(self) -> list[int]:
        return sorted(self.tree_of)

    @classmethod
    def collect(cls, selected: QuerySet, requested_ids: Sequence[int]) -> "ExportedSessions":
        """Find the sessions an export of `requested_ids` carries.

        Args:
            selected: The requested sessions, already scoped to the caller's organization.
                Their sub-sessions are found through them, so they are in it too.
            requested_ids: The ids in the order the job was asked for.
        """
        parent_of: dict[int, int | None] = dict(selected.values_list("id", "parent_session_id"))
        children_of: dict[int, list[int]] = defaultdict(list)
        level = list(parent_of)
        while level:
            next_level = []
            for batch in batched(level, SUB_SESSION_LOOKUP_BATCH):
                sub_sessions = (
                    Session.objects.filter(parent_session_id__in=batch)
                    .order_by("id")
                    .values_list("id", "parent_session_id")
                )
                for session_id, parent_id in sub_sessions:
                    children_of[parent_id].append(session_id)
                    if session_id not in parent_of:
                        parent_of[session_id] = parent_id
                        next_level.append(session_id)
            level = next_level

        return cls(
            depth_first_ids=_depth_first(requested_ids, parent_of, children_of),
            tree_of={session_id: _tree_of(session_id, parent_of) for session_id in parent_of},
        )


def iter_session_entries(session_ids: Sequence[int]) -> Iterator[dict]:
    """Yield the export entry of each session, in the order of `session_ids`.

    A session deleted since its ids were collected is left out, as `ExportService`
    leaves out an entity it no longer finds.
    """
    for chunk in batched(session_ids, SESSION_CHUNK_SIZE):
        sessions = SessionStrategy.export_sessions().in_bulk(chunk)
        position = Case(
            *(
                When(session_id=session_id, then=Value(index))
                for index, session_id in enumerate(chunk)
            ),
            output_field=IntegerField(),
        )
        messages = (
            SessionStrategy.export_messages()
            .filter(session_id__in=chunk)
            .alias(chunk_position=position)
            .order_by("chunk_position", "created_at", "id")
            .iterator(chunk_size=MESSAGE_FETCH_SIZE)
        )
        pending = next(messages, None)
        for session_id in chunk:
            session_messages = []
            while pending is not None and pending.session_id == session_id:
                session_messages.append(pending)
                pending = next(messages, None)
            session = sessions.get(session_id)
            if session is not None:
                yield SessionStrategy.export_entry(session, session_messages)


def _depth_first(
    requested_ids: Sequence[int],
    parent_of: dict[int, int | None],
    children_of: dict[int, list[int]],
) -> list[int]:
    ordered = []
    entered = set()
    for requested_id in requested_ids:
        if requested_id in entered or requested_id not in parent_of:
            continue
        entered.add(requested_id)
        # Iterative, so a deeply nested subflow cannot exhaust the recursion limit.
        stack = [(requested_id, iter(children_of[requested_id]))]
        while stack:
            session_id, children = stack[-1]
            child_id = next((child for child in children if child not in entered), None)
            if child_id is None:
                stack.pop()
                ordered.append(session_id)
                continue
            entered.add(child_id)
            stack.append((child_id, iter(children_of[child_id])))
    return ordered


def _tree_of(session_id: int, parent_of: dict[int, int | None]) -> int:
    seen = {session_id}
    while (parent_id := parent_of[session_id]) in parent_of and parent_id not in seen:
        seen.add(parent_id)
        session_id = parent_id
    return session_id
