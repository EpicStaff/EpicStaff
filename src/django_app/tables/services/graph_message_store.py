"""Stores the graph session messages crew streams, and finishes a session on ``graph_end``."""

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import redis
from django.db import DataError, IntegrityError, InterfaceError, OperationalError, transaction
from pydantic import ValidationError
from src.shared.models import GraphSessionMessageData
from src.shared.redis_keys import session_messages_channel
from tables.models import GraphSessionMessage, Session
from tables.models.session_models import SessionPrincipal, SessionTrigger
from tables.services.session_token_usage import (
    COST_FIELD,
    TOKEN_COUNT_FIELDS,
    MessageTokenUsage,
    SessionTokenUsageCounter,
    empty_token_usage,
    sum_token_usage,
)
from tables.services.trigger_spec import TriggerSpec
from tables.utils.base64_preview import trim_base64_file_data_in_json
from utils.logger import logger

# Rows per INSERT statement. Building the statement for one ~300 KB message costs the
# worker ~1.5-2 MB, so this bounds the memory of one statement, not of the batch.
INSERT_BATCH_SIZE = 10

# Root-session rows fetched per round trip while copying them into subgraph sessions.
COPY_READ_CHUNK_SIZE = 10

# Statuses after which nothing else updates a session's token total, so a late message
# carrying token usage must update it here.
FINISHED_SESSION_STATUSES = (
    Session.SessionStatus.END,
    Session.SessionStatus.ERROR,
    Session.SessionStatus.STOP,
    Session.SessionStatus.EXPIRED,
)

# Retrying after these can succeed, so they must reach the caller, which redelivers.
TRANSIENT_DATABASE_ERRORS = (OperationalError, InterfaceError)


@dataclass
class _ReceivedMessage:
    data: GraphSessionMessageData
    payload: str
    uuid: str

    @property
    def session_id(self) -> int:
        return self.data.session_id

    @property
    def is_graph_end(self) -> bool:
        return self.data.message_data.get("message_type") == "graph_end"


@dataclass
class _SubgraphRun:
    execution_id: str
    graph_id: int | None
    parent_execution_id: str | None
    input: dict
    output: dict = field(default_factory=dict)
    finished: bool = False


class GraphMessageStore:
    """Persists batches of graph session messages and announces them to SSE streams.

    Safe to call again with the same messages (the stream redelivers a batch that was
    not acknowledged): a message already stored is neither stored nor counted twice,
    and the ``graph_end`` follow-up only creates what does not exist yet.
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client
        self.token_usage_counter = SessionTokenUsageCounter(redis_client)

    def persist_batch(self, payloads: list[str]) -> None:
        """Store one batch of messages, in order, then announce each stored one.

        A malformed message, or one whose session was deleted, is logged and skipped:
        retrying it can never succeed. So is a message the database rejects, without
        losing the other messages of its session or of the batch.

        After the rows are committed, this adds the usage of every message not counted
        yet to its session's total, finishes every session that sent ``graph_end``
        (token total and subgraph sessions), refreshes the stored total of finished
        sessions the batch carries usage for, and publishes each received string on its
        session's messages channel, unchanged unless it carries base64 file data, which
        is cut to a preview once here rather than by every SSE stream.

        Raises:
            django.db.OperationalError, django.db.InterfaceError, redis.RedisError:
                Transient failures. Nothing is lost: the caller must not acknowledge
                the batch, and calling again with it completes the work.
        """
        messages = self._parse(payloads)
        messages = self._drop_messages_of_deleted_sessions(messages)
        rejected_uuids = self._insert(self._exclude_stored(messages))
        if rejected_uuids:
            messages = [message for message in messages if message.uuid not in rejected_uuids]

        session_ids_with_usage = self._add_token_usage(messages)
        self._finish_sessions(messages, session_ids_with_usage)
        self._publish(messages)

    @staticmethod
    def _parse(payloads: list[str]) -> list[_ReceivedMessage]:
        messages = []
        seen_uuids = set()
        for payload in payloads:
            try:
                data = GraphSessionMessageData.model_validate_json(payload)
                message_uuid = str(UUID(data.uuid))
            except (ValidationError, ValueError) as error:
                logger.error("Skipping a malformed graph message: {}", error)
                continue
            # crew retries a failed XADD, so one message can be in a batch twice.
            if message_uuid in seen_uuids:
                logger.debug("Skipping a repeated graph message {}", message_uuid)
                continue
            seen_uuids.add(message_uuid)
            messages.append(_ReceivedMessage(data=data, payload=payload, uuid=message_uuid))
        return messages

    @staticmethod
    def _drop_messages_of_deleted_sessions(
        messages: list[_ReceivedMessage],
    ) -> list[_ReceivedMessage]:
        existing_session_ids = set(
            Session.objects.filter(id__in={message.session_id for message in messages}).values_list(
                "id", flat=True
            )
        )
        kept = [message for message in messages if message.session_id in existing_session_ids]
        if len(kept) < len(messages):
            logger.warning(
                "Skipping {} graph messages of deleted sessions {}",
                len(messages) - len(kept),
                sorted({message.session_id for message in messages} - existing_session_ids),
            )
        return kept

    @staticmethod
    def _exclude_stored(messages: list[_ReceivedMessage]) -> list[_ReceivedMessage]:
        # A redelivered batch may be partly stored already; its rows need not be sent again.
        stored_uuids = {
            str(stored_uuid)
            for stored_uuid in GraphSessionMessage.objects.filter(
                uuid__in=[message.uuid for message in messages]
            ).values_list("uuid", flat=True)
        }
        return [message for message in messages if message.uuid not in stored_uuids]

    def _insert(self, messages: list[_ReceivedMessage]) -> set[str]:
        """Insert the rows in stream order; return the uuids of the rows rejected."""
        if not messages:
            return set()
        try:
            self._insert_rows(messages)
            return set()
        except (IntegrityError, DataError) as error:
            logger.warning("Graph message batch rejected ({}); storing it per session", error)

        messages_by_session = defaultdict(list)
        for message in messages:
            messages_by_session[message.session_id].append(message)

        rejected_uuids = set()
        for session_id, session_messages in messages_by_session.items():
            try:
                self._insert_rows(session_messages)
            except (IntegrityError, DataError) as error:
                logger.warning(
                    "Graph messages of session {} rejected ({}); storing them one by one",
                    session_id,
                    error,
                )
                rejected_uuids |= self._insert_one_by_one(session_messages)
        return rejected_uuids

    def _insert_one_by_one(self, messages: list[_ReceivedMessage]) -> set[str]:
        # The bad row is dropped alone, so the session's graph_end still lands.
        rejected_uuids = set()
        for message in messages:
            try:
                self._insert_rows([message])
            except (IntegrityError, DataError):
                logger.exception(
                    "Dropping graph message {} of session {}: the database rejected it",
                    message.uuid,
                    message.session_id,
                )
                rejected_uuids.add(message.uuid)
        return rejected_uuids

    @staticmethod
    def _insert_rows(messages: list[_ReceivedMessage]) -> None:
        with transaction.atomic():
            GraphSessionMessage.objects.bulk_create(
                [_to_row(message) for message in messages],
                ignore_conflicts=True,
                batch_size=INSERT_BATCH_SIZE,
            )

    def _add_token_usage(self, messages: list[_ReceivedMessage]) -> set[int]:
        """Count the usage of the stored messages not counted yet; return the sessions
        the batch carries any usage for.

        Every stored message of the batch is offered, not only the rows inserted now:
        a redelivered batch's rows can be stored while their usage never reached Redis.
        """
        message_usages = []
        for message in messages:
            token_usage = sum_token_usage([message.data.message_data])
            if any(token_usage.values()):
                message_usages.append(
                    MessageTokenUsage(
                        session_id=message.session_id,
                        message_uuid=message.uuid,
                        token_usage=token_usage,
                    )
                )
        self.token_usage_counter.add_once(message_usages)
        return {usage.session_id for usage in message_usages}

    def _finish_sessions(
        self, messages: list[_ReceivedMessage], session_ids_with_usage: set[int]
    ) -> None:
        graph_end_session_ids = {message.session_id for message in messages if message.is_graph_end}
        # A message can arrive after its session's END/ERROR status was stored (the
        # status travels on pub/sub and is not held back by this stream's backlog), so
        # its usage must still reach that session's stored total. A redelivered batch
        # refreshes it too: the earlier attempt may have counted without storing.
        self._store_token_totals(graph_end_session_ids, session_ids_with_usage)

        for session_id in sorted(graph_end_session_ids):
            try:
                self.create_subgraph_sessions(session_id)
            except TRANSIENT_DATABASE_ERRORS:
                raise
            except Exception:
                # Retrying cannot fix it, and raising would hold back graph_end, which
                # tells the SSE clients the run is over, on every redelivery.
                logger.exception("Could not create the subgraph sessions of session {}", session_id)

    def _store_token_totals(
        self, graph_end_session_ids: set[int], session_ids_with_usage: set[int]
    ) -> None:
        candidate_ids = graph_end_session_ids | session_ids_with_usage
        if not candidate_ids:
            return
        # The row lock orders this against the status handler, which reads the hash
        # under the same lock: whichever of the two runs second stores the full total.
        # NO KEY UPDATE: it does not wait for the KEY SHARE locks of message inserts.
        with transaction.atomic():
            sessions = (
                Session.objects.select_for_update(no_key=True)
                .filter(id__in=candidate_ids)
                .order_by("id")
                .only("id", "status", "status_data")
            )
            for session in sessions:
                if (
                    session.id not in graph_end_session_ids
                    and session.status not in FINISHED_SESSION_STATUSES
                ):
                    continue
                token_usage = self.token_usage_counter.read(session.id)
                Session.objects.filter(id=session.id).update(
                    token_usage=token_usage,
                    status_data={**(session.status_data or {}), "total_token_usage": token_usage},
                )

    def _publish(self, messages: list[_ReceivedMessage]) -> None:
        if not messages:
            return
        pipeline = self.redis_client.pipeline(transaction=False)
        for message in messages:
            pipeline.publish(
                session_messages_channel(message.session_id),
                trim_base64_file_data_in_json(message.payload),
            )
        pipeline.execute()

    def create_subgraph_sessions(self, root_session_id: int) -> None:
        """Create the sessions of the subgraphs a finished root session ran.

        Finds the subgraph_start/finish pairs among the root session's messages,
        creates a Session per subgraph (parents before children), copies to each the
        messages tagged with its execution id, and stores each subgraph's token usage.
        Does nothing when the root session already has child sessions, so a
        redelivered ``graph_end`` creates them once.

        Only messages run inside a subgraph are read whole, and the root session row is
        locked only while the subgraph sessions and their message copies are written:
        a run without subgraphs costs one query and no lock.
        """
        if not _has_subgraph_start(root_session_id):
            return
        subgraph_runs = _read_subgraph_runs(root_session_id)
        if not subgraph_runs:
            return
        with transaction.atomic():
            self._create_subgraph_sessions(root_session_id, subgraph_runs)

    def _create_subgraph_sessions(
        self, root_session_id: int, subgraph_runs: list[_SubgraphRun]
    ) -> None:
        # The lock makes the check below and the writes one step for concurrent callers.
        root_session = (
            Session.objects.select_for_update(no_key=True)
            .filter(pk=root_session_id)
            .only("id", "time_to_live", "graph_schema")
            .first()
        )
        if root_session is None:
            logger.warning("Root session {} not found", root_session_id)
            return
        if Session.objects.filter(parent_session_id=root_session_id).exists():
            logger.debug("Subgraph sessions already exist for root session {}", root_session_id)
            return

        sessions_by_execution_id = {}
        # Forward order: a parent subgraph's session exists before its children's.
        for run in subgraph_runs:
            parent_session = sessions_by_execution_id.get(run.parent_execution_id)
            sessions_by_execution_id[run.execution_id] = Session.objects.create(
                graph_id=run.graph_id,
                status=Session.SessionStatus.END if run.finished else Session.SessionStatus.ERROR,
                parent_session_id=parent_session.pk if parent_session else root_session_id,
                variables=run.output or run.input,
                time_to_live=root_session.time_to_live,
                graph_schema=root_session.graph_schema,
                status_data={"variables": run.output},
            )
        sessions = list(sessions_by_execution_id.values())

        SessionTrigger.objects.bulk_create(
            [
                SessionTrigger(
                    session=session,
                    **TriggerSpec.parent_flow(session.parent_session_id).to_fields(),
                )
                for session in sessions
            ]
        )
        root_principal_fields = SessionPrincipal.objects.filter(session_id=root_session_id).values(
            "kind", "user_id", "api_key_id", "email"
        ).first() or {"kind": SessionPrincipal.ActionKind.UNKNOWN}
        SessionPrincipal.objects.bulk_create(
            [SessionPrincipal(session=session, **root_principal_fields) for session in sessions]
        )

        usage_by_execution_id = _copy_messages_into_subgraph_sessions(
            root_session_id, sessions_by_execution_id
        )
        for execution_id, session in sessions_by_execution_id.items():
            token_usage = usage_by_execution_id.get(execution_id, empty_token_usage())
            session.token_usage = token_usage
            session.status_data = {**session.status_data, "total_token_usage": token_usage}
        Session.objects.bulk_update(sessions, ["token_usage", "status_data"])


def _has_subgraph_start(root_session_id: int) -> bool:
    return GraphSessionMessage.objects.filter(
        session_id=root_session_id, message_data__message_type="subgraph_start"
    ).exists()


def _read_subgraph_runs(root_session_id: int) -> list[_SubgraphRun]:
    """Return the root session's subgraph runs in start order, parents before children.

    Reads only the fields the sessions are created from: a start message also carries
    the whole graph state, which stays in the database.
    """
    rows = (
        GraphSessionMessage.objects.filter(
            session_id=root_session_id,
            message_data__message_type__in=["subgraph_start", "subgraph_finish"],
        )
        .order_by("id")
        .values_list(
            "message_data__message_type",
            "message_data__subgraph_execution_id",
            "message_data__subgraph_id",
            "message_data__subgraph_execution_ids",
            "message_data__input",
            "message_data__output",
        )
    )
    runs_by_execution_id = {}
    finished_outputs = {}
    for message_type, execution_id, graph_id, ancestor_ids, run_input, output in rows:
        if not execution_id:
            continue
        if message_type == "subgraph_start":
            # Its own tags are its ancestors, innermost first: its parent is the first.
            runs_by_execution_id[execution_id] = _SubgraphRun(
                execution_id=execution_id,
                graph_id=graph_id,
                parent_execution_id=ancestor_ids[0] if ancestor_ids else None,
                input=run_input or {},
            )
        else:
            finished_outputs[execution_id] = output or {}

    for execution_id, output in finished_outputs.items():
        run = runs_by_execution_id.get(execution_id)
        if run is not None:
            run.finished = True
            run.output = output
    return list(runs_by_execution_id.values())


def _copy_messages_into_subgraph_sessions(
    root_session_id: int, sessions_by_execution_id: dict[str, Session]
) -> dict[str, dict]:
    """Copy each message run inside a subgraph into that subgraph's session and into
    the session of every subgraph enclosing it; return each subgraph's token usage.

    A message belongs to a subgraph when the subgraph's execution id is among its
    ``subgraph_execution_ids``. Only a message run inside some subgraph has any, and
    exactly those have a ``parent_subgraph_execution_id`` (the first of them), so the
    indexed column selects the candidates and the root's own messages are never read.
    """
    usage_by_execution_id = defaultdict(empty_token_usage)
    pending_copies = []
    rows = (
        GraphSessionMessage.objects.filter(
            session_id=root_session_id, parent_subgraph_execution_id__isnull=False
        )
        .order_by("id")
        .only("created_at", "name", "execution_order", "message_data", "node_type")
        .iterator(chunk_size=COPY_READ_CHUNK_SIZE)
    )
    for message in rows:
        message_data = message.message_data or {}
        execution_ids = message_data.get("subgraph_execution_ids") or []
        message_usage = None
        for position, execution_id in enumerate(execution_ids):
            session = sessions_by_execution_id.get(execution_id)
            if session is None:
                continue
            pending_copies.append(
                _copy_into_subgraph_session(message, execution_ids[:position], session.pk)
            )
            if message_usage is None:
                message_usage = sum_token_usage([message_data])
            _add_usage(usage_by_execution_id[execution_id], message_usage)
        if len(pending_copies) >= INSERT_BATCH_SIZE:
            GraphSessionMessage.objects.bulk_create(pending_copies, batch_size=INSERT_BATCH_SIZE)
            pending_copies = []
    GraphSessionMessage.objects.bulk_create(pending_copies, batch_size=INSERT_BATCH_SIZE)
    return usage_by_execution_id


def _add_usage(total_usage: dict, token_usage: dict) -> None:
    for usage_field in (*TOKEN_COUNT_FIELDS, COST_FIELD):
        total_usage[usage_field] += token_usage[usage_field]


def _parent_subgraph_execution_id(message_data: dict) -> str | None:
    subgraph_execution_ids = message_data.get("subgraph_execution_ids") or []
    return subgraph_execution_ids[0] if subgraph_execution_ids else None


def _to_row(message: _ReceivedMessage) -> GraphSessionMessage:
    data = message.data
    return GraphSessionMessage(
        session_id=data.session_id,
        created_at=data.timestamp,
        name=data.name,
        execution_order=data.execution_order,
        message_data=data.message_data,
        node_type=data.node_type,
        uuid=message.uuid,
        parent_subgraph_execution_id=_parent_subgraph_execution_id(data.message_data),
    )


def _copy_into_subgraph_session(
    message: GraphSessionMessage, inner_execution_ids: list[str], subgraph_session_id: int
) -> GraphSessionMessage:
    # Within the subgraph's own session, only the subgraphs nested inside it are ancestors.
    return GraphSessionMessage(
        session_id=subgraph_session_id,
        created_at=message.created_at,
        name=message.name,
        execution_order=message.execution_order,
        message_data={
            **(message.message_data or {}),
            "subgraph_execution_ids": inner_execution_ids,
        },
        node_type=message.node_type,
        uuid=uuid4(),
        parent_subgraph_execution_id=inner_execution_ids[0] if inner_execution_ids else None,
    )
