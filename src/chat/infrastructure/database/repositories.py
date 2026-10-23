from __future__ import (
    annotations,  # a `list` method in the class body shadows the builtin in later annotations
)

import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from common.utils import utcnow
from domain.enums import (
    BindingStyle,
    InboxOrder,
    InboxSection,
    Mode,
    OnResponseTimeout,
    Role,
    RunState,
    Stream,
)
from domain.errors import AliasTakenError
from domain.models import (
    Binding,
    CallbackReceipt,
    Conversation,
    ConversationEvent,
    InboxBadge,
    Message,
    VisitorToken,
)
from domain.ports.repositories import (
    AbstractBindingRepository,
    AbstractConversationRepository,
    AbstractEventRepository,
    AbstractMessageRepository,
    AbstractOperatorAliasRepository,
    AbstractOperatorProfileRepository,
    AbstractReceiptRepository,
    AbstractUsageRepository,
    AbstractVisitorNumberRepository,
    AbstractVisitorTokenRepository,
)
from domain.public_name import public_name_key
from domain.search import InboxSearch
from sqlalchemy import (
    DateTime,
    Interval,
    and_,
    any_,
    delete,
    func,
    insert,
    literal,
    literal_column,
    or_,
    select,
    true,
    tuple_,
    update,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.mappers import to_domain, to_row, values_of
from infrastructure.database.models import (
    BindingRow,
    CallbackReceiptRow,
    ConversationEventRow,
    ConversationRow,
    DailyUsageRow,
    MessageRow,
    OperatorAliasRow,
    OperatorProfileRow,
    VisitorNumberCounterRow,
    VisitorTokenRow,
)

HISTORY_ROLES = (Role.USER.value, Role.ASSISTANT.value, Role.OPERATOR.value)
# What a past action keeps in a run's `chat_history`: which button, and what it said. An action
# may carry up to CHAT_ACTION_MAX_BYTES (edited tables), and every later run repeats the history,
# so its `params`, `tables` and anything else stay only in the run it started.
HISTORY_ACTION_KEYS = ("type", "action", "text")


def _history_action(action: dict) -> dict:
    return {key: action[key] for key in HISTORY_ACTION_KEYS if key in action}


@dataclass(frozen=True)
class _SectionSpec:
    """How one inbox section reads.

    `conditions` are exactly the predicate of the section's partial indexes, as bare columns:
    a bound parameter (`is_test = $3`, `status = $4`) would not imply an index's `NOT is_test`
    or `closed_at IS NULL` under a generic plan, so the index would be skipped once the
    statement is prepared. Hence open and closed are told apart by `closed_at`, not `status`.
    """

    conditions: tuple
    # The one direction the section is read in, whatever the caller asks: oldest key first
    # for a queue, newest first for Closed. None lets `order` pick.
    fixed_order: InboxOrder | None
    # Rows can have a holder, so Mine and the holder-name search can match them.
    held: bool
    # Rows can be signed, so the signed-id search can match them; test conversations never are.
    signed: bool


_OPEN = ConversationRow.closed_at.is_(None)
# A closed conversation never waits, so Waiting needs no `closed_at` test.
_WAITING = (ConversationRow.visitor_waiting_since.is_not(None), ~ConversationRow.is_test)
_IN_PROGRESS = (
    ConversationRow.assigned_operator_id.is_not(None),
    ConversationRow.visitor_waiting_since.is_(None),
    ConversationRow.last_message_at.is_not(None),
    ~ConversationRow.is_test,
    _OPEN,
)
_BOT = (
    ConversationRow.handoff_at.is_(None),
    ConversationRow.last_message_at.is_not(None),
    ~ConversationRow.is_test,
    _OPEN,
)
_CLOSED = (
    ConversationRow.closed_at.is_not(None),
    ConversationRow.last_message_at.is_not(None),
    ~ConversationRow.is_test,
)
_SECTIONS = {
    InboxSection.WAITING: _SectionSpec(
        _WAITING, fixed_order=InboxOrder.OLDEST, held=True, signed=True
    ),
    InboxSection.IN_PROGRESS: _SectionSpec(_IN_PROGRESS, fixed_order=None, held=True, signed=True),
    InboxSection.HUMAN: _SectionSpec(
        (ConversationRow.handoff_at.is_not(None), ~ConversationRow.is_test, _OPEN),
        fixed_order=InboxOrder.OLDEST,
        held=True,
        signed=True,
    ),
    InboxSection.BOT: _SectionSpec(_BOT, fixed_order=None, held=False, signed=True),
    # Open and closed tests alike: an operator's tries stay together.
    InboxSection.TEST: _SectionSpec(
        (ConversationRow.is_test, ConversationRow.last_message_at.is_not(None)),
        fixed_order=None,
        held=True,
        signed=False,
    ),
    # A closed conversation keeps its last holder, so Mine and the holder search reach it.
    InboxSection.CLOSED: _SectionSpec(
        _CLOSED, fixed_order=InboxOrder.NEWEST, held=True, signed=True
    ),
}
# Seconds in a binding column, as an interval the timers add to a timestamp.
_SECOND = literal_column("interval '1 second'", Interval)


def _like_escaped(text: str) -> str:
    """`text` with LIKE's wildcards and escape character taken literally (`ESCAPE '\\'`)."""
    return re.sub(r"([\\%_])", r"\\\1", text)


# The last code point, a noncharacter no id contains: a prefix followed by it is above every string
# that starts with the prefix, in byte (UTF-8) order.
_LAST_CODE_POINT = chr(0x10FFFF)


def _search_matches(
    spec: _SectionSpec,
    org_id: int,
    binding_id: UUID | None,
    search: InboxSearch,
    holder_ids: list[int],
) -> list:
    """The ways `search` can match a row of the section, each one an index can answer.

    A way the section's rows can never match is left out, and so is the holder's name when it
    names nobody. Each way stays an index condition, so the plan can combine them (BitmapOr)
    rather than read the section in order and filter it. Postgres lowers both sides of every
    comparison.

    Args:
        holder_ids: The operators whose name contains the search, looked up beforehand: as a
            literal list its length is known to the plan, where a subquery counts as ten.
    """
    matches = []
    if search.visitor_number is not None:
        # The (binding_id, visitor_number) unique index: the desk, or each desk of the org.
        desks = (
            ConversationRow.binding_id == binding_id
            if binding_id is not None
            else ConversationRow.binding_id
            == any_(
                func.array(
                    select(BindingRow.id).where(BindingRow.org_id == org_id).scalar_subquery()
                )
            )
        )
        matches.append(and_(desks, ConversationRow.visitor_number == search.visitor_number))
    if spec.signed:
        # The prefix as the byte-order range LIKE 'q%' stands for, on the text_pattern_ops index.
        # Not LIKE itself: a prepared statement's generic plan cannot turn a LIKE parameter into
        # an index range, and would read every signed row of the org instead.
        subject, prefix = func.lower(ConversationRow.subject), func.lower(search.text)
        matches.append(
            and_(
                ConversationRow.is_signed,
                subject.op("~>=~", is_comparison=True)(prefix),
                # Grouped: Postgres would read `a ~<~ b || c` as `(a ~<~ b) || c`.
                subject.op("~<~", is_comparison=True)(prefix.concat(_LAST_CODE_POINT).self_group()),
            )
        )
    if spec.held and holder_ids:
        # IS NOT NULL spelled out: it lets the Mine indexes, which only hold held rows, answer.
        matches.append(
            and_(
                ConversationRow.assigned_operator_id.is_not(None),
                ConversationRow.assigned_operator_id.in_(holder_ids),
            )
        )
    return matches


class _Repository:
    def __init__(self, session: AsyncSession):
        self._session = session


class BindingRepository(_Repository, AbstractBindingRepository):
    async def add(self, binding: Binding) -> None:
        self._session.add(to_row(binding, BindingRow))
        await self._session.flush()

    async def get(
        self,
        binding_id: UUID,
        org_id: int | None = None,
        *,
        for_update: bool = False,
        for_share: bool = False,
    ) -> Binding | None:
        query = select(BindingRow).where(BindingRow.id == binding_id)
        if org_id is not None:
            query = query.where(BindingRow.org_id == org_id)
        if for_update:
            query = query.with_for_update()
        elif for_share:
            query = query.with_for_update(read=True)
        row = (await self._session.execute(query)).scalar_one_or_none()
        return to_domain(row, Binding) if row else None

    async def get_with_operator_alias(
        self, binding_id: UUID, user_id: int
    ) -> tuple[Binding, str | None] | None:
        found = (
            await self._session.execute(
                select(BindingRow, OperatorAliasRow.alias)
                .outerjoin(
                    OperatorAliasRow,
                    and_(
                        OperatorAliasRow.binding_id == BindingRow.id,
                        OperatorAliasRow.user_id == user_id,
                    ),
                )
                .where(BindingRow.id == binding_id)
            )
        ).one_or_none()
        if found is None:
            return None
        row, alias = found
        return to_domain(row, Binding), alias

    async def get_by_public_key(
        self, public_key: str, *, for_share: bool = False
    ) -> Binding | None:
        query = select(BindingRow).where(BindingRow.public_key == public_key)
        if for_share:
            query = query.with_for_update(read=True)
        row = (await self._session.execute(query)).scalar_one_or_none()
        return to_domain(row, Binding) if row else None

    async def list(self, org_id: int) -> list[Binding]:
        rows = (
            await self._session.execute(
                select(BindingRow).where(BindingRow.org_id == org_id).order_by(BindingRow.id)
            )
        ).scalars()
        return [to_domain(row, Binding) for row in rows]

    async def update(self, binding: Binding) -> None:
        await self._session.execute(
            update(BindingRow)
            .where(BindingRow.id == binding.id)
            .values(**values_of(binding, exclude=("id",)))
        )

    async def set_broken_reason(self, binding_id: UUID, reason: str | None) -> None:
        await self._session.execute(
            update(BindingRow)
            .where(BindingRow.id == binding_id)
            .values(broken_reason=reason, updated_at=utcnow())
        )

    async def delete(self, binding_id: UUID, org_id: int) -> bool:
        result = await self._session.execute(
            delete(BindingRow).where(BindingRow.id == binding_id, BindingRow.org_id == org_id)
        )
        return result.rowcount == 1


class ConversationRepository(_Repository, AbstractConversationRepository):
    async def add(self, conversation: Conversation) -> None:
        self._session.add(to_row(conversation, ConversationRow))
        await self._session.flush()

    async def _one(
        self, *conditions, for_update: bool = False, skip_locked: bool = False
    ) -> Conversation | None:
        query = select(ConversationRow).where(*conditions)
        if for_update:
            query = query.with_for_update(skip_locked=skip_locked)
        row = (await self._session.execute(query)).scalar_one_or_none()
        return to_domain(row, Conversation) if row else None

    async def get(
        self,
        conversation_id: UUID,
        org_id: int | None = None,
        *,
        for_update: bool = False,
        skip_locked: bool = False,
    ) -> Conversation | None:
        conditions = [ConversationRow.id == conversation_id]
        if org_id is not None:
            conditions.append(ConversationRow.org_id == org_id)
        return await self._one(*conditions, for_update=for_update, skip_locked=skip_locked)

    async def get_open_by_subject(
        self, binding_id: UUID, subject: str, *, for_update: bool = False
    ) -> Conversation | None:
        return await self._one(
            ConversationRow.binding_id == binding_id,
            ConversationRow.subject == subject,
            _OPEN,
            for_update=for_update,
        )

    async def claim_run_slot(self, conversation_id: UUID) -> bool:
        result = await self._session.execute(
            update(ConversationRow)
            .where(
                ConversationRow.id == conversation_id,
                ConversationRow.run_state == RunState.IDLE.value,
                _OPEN,
            )
            .values(run_state=RunState.STARTING.value, active_since=utcnow())
            .returning(ConversationRow.id)
        )
        return result.scalar_one_or_none() is not None

    async def update(self, conversation: Conversation) -> None:
        await self._session.execute(
            update(ConversationRow)
            .where(ConversationRow.id == conversation.id)
            .values(**values_of(conversation, exclude=("id",)))
        )

    async def list(
        self,
        org_id: int,
        binding_id: UUID | None,
        section: InboxSection,
        limit: int,
        after: tuple[datetime, UUID] | None,
        mode: Mode | None = None,
        *,
        order: InboxOrder = InboxOrder.NEWEST,
        holder_id: int | None = None,
        search: InboxSearch | None = None,
    ) -> list[Conversation]:
        spec = _SECTIONS[section]
        if holder_id is not None and not spec.held:
            return []
        conditions = [*spec.conditions, ConversationRow.org_id == org_id]
        if binding_id is not None:
            conditions.append(ConversationRow.binding_id == binding_id)
        if mode is not None:
            conditions.append(ConversationRow.mode == mode.value)
        if holder_id is not None:
            conditions.append(ConversationRow.assigned_operator_id == holder_id)
        if search is not None:
            holder_ids = await self._operators_named(org_id, search.text) if spec.held else []
            matches = _search_matches(spec, org_id, binding_id, search, holder_ids)
            if not matches:
                return []
            conditions.append(or_(*matches))
        keyset = (getattr(ConversationRow, section.key_field), ConversationRow.id)
        ascending = (spec.fixed_order or order) == InboxOrder.OLDEST
        if after is not None:
            # Both key columns sort the same direction, so "after" is a plain row comparison.
            row_key = tuple_(*keyset)
            conditions.append(row_key > after if ascending else row_key < after)
        ordering = keyset if ascending else tuple(column.desc() for column in keyset)
        # The limit is written into the statement: as a parameter, a prepared statement's generic
        # plan takes it for a tenth of the rows and walks a whole section in order hoping to stop
        # early, where a selective search should fetch its few rows through their indexes.
        rows = (
            await self._session.execute(
                select(ConversationRow)
                .where(*conditions)
                .order_by(*ordering)
                .limit(literal(limit, literal_execute=True))
            )
        ).scalars()
        return [to_domain(row, Conversation) for row in rows]

    async def _operators_named(self, org_id: int, text: str) -> list[int]:
        """The org's operators whose display name contains `text`, case-insensitively.

        Only the org's own names are read (its range of the primary key), so whether anyone
        matches, and how long finding out takes, depends on nothing outside the org: the search
        is no oracle for other orgs' operators.
        """
        pattern = func.concat("%", func.lower(_like_escaped(text)), "%")
        rows = await self._session.execute(
            select(OperatorProfileRow.user_id).where(
                OperatorProfileRow.org_id == org_id,
                func.lower(OperatorProfileRow.display_name).like(pattern, escape="\\"),
            )
        )
        return list(rows.scalars())

    async def badges(self, org_id: int) -> list[InboxBadge]:
        rows = await self._session.execute(
            select(
                ConversationRow.id,
                ConversationRow.binding_id,
                ConversationRow.assigned_operator_id,
            ).where(*_SECTIONS[InboxSection.WAITING].conditions, ConversationRow.org_id == org_id)
        )
        return [InboxBadge(*row) for row in rows]

    async def unanswered_past_response_time(self, now: datetime, limit: int) -> list[UUID]:
        desks = (
            select(BindingRow.id, BindingRow.response_time_seconds.label("seconds"))
            .where(BindingRow.on_response_timeout == OnResponseTimeout.HANDBACK.value)
            .subquery()
        )
        return await self._overdue_per_desk(
            desks, ConversationRow.visitor_waiting_since, _WAITING, now, limit
        )

    async def inactive_past_close_after(self, now: datetime, limit: int) -> list[UUID]:
        desks = (
            select(BindingRow.id, BindingRow.close_after_seconds.label("seconds"))
            .where(BindingRow.style == BindingStyle.SUPPORT.value)
            .subquery()
        )
        conditions = (
            _OPEN,
            ConversationRow.last_message_at.is_not(None),
            ~ConversationRow.is_test,
            # Written into the statement, so a generic plan still matches the index's predicate.
            ConversationRow.run_state == literal(RunState.IDLE.value, literal_execute=True),
        )
        return await self._overdue_per_desk(
            desks, ConversationRow.last_message_at, conditions, now, limit
        )

    async def _overdue_per_desk(
        self, desks, key, conditions: tuple, now: datetime, limit: int
    ) -> list[UUID]:
        """Up to `limit` ids whose `key` is more than each desk's `seconds` before `now`, in
        deadline order (`key + seconds`), so a desk with a short timeout is never starved by
        one with a long timeout.

        `desks` is a subquery of the desks the rule acts on, with `id` and `seconds` columns.
        Each desk is read as its own range of the partial index `conditions` match, in index
        order, stopping at `limit` (a LATERAL read): desks the rule leaves alone are never read,
        however many conversations pile up there. Two planner settings hold for the rest of the
        transaction: no bitmap scans (with a backlog, a plan made for the actual `now` would
        bitmap read and sort a desk's whole overdue range rather than stop at the limit), and no
        JIT (it would compile this cheap read on every pass).
        """
        await self._session.execute(sql_text("SET LOCAL enable_bitmapscan = off"))
        await self._session.execute(sql_text("SET LOCAL jit = off"))
        window = desks.c.seconds * _SECOND
        # timestamptz explicitly: inferred from the value it would be cast to a plain
        # timestamp, read in the server's time zone.
        deadline = literal(now, DateTime(timezone=True)) - window
        # The limits are written into the statement, as in `list`: as parameters a generic plan
        # would take them for a tenth of the rows.
        batch = literal(limit, literal_execute=True)
        per_desk = (
            select(ConversationRow.id, (key + window).label("due_at"))
            .where(ConversationRow.binding_id == desks.c.id, *conditions, key < deadline)
            .order_by(key, ConversationRow.id)
            .limit(batch)
            .lateral()
        )
        rows = await self._session.execute(
            select(per_desk.c.id)
            .select_from(desks)
            .join(per_desk, true())
            .order_by(per_desk.c.due_at, per_desk.c.id)
            .limit(batch)
        )
        return list(rows.scalars())

    async def stale_runs(self, older_than: datetime) -> list[tuple[Conversation, int]]:
        rows = await self._session.execute(
            select(ConversationRow, CallbackReceiptRow.session_id)
            .join(CallbackReceiptRow, CallbackReceiptRow.run_id == ConversationRow.active_run_id)
            .where(
                ConversationRow.run_state == RunState.RUNNING.value,
                ConversationRow.active_since < older_than,
            )
        )
        return [(to_domain(row, Conversation), session_id) for row, session_id in rows]

    async def unconfirmed_starts(self, older_than: datetime) -> list[Conversation]:
        rows = (
            await self._session.execute(
                select(ConversationRow).where(
                    ConversationRow.run_state == RunState.STARTING.value,
                    ConversationRow.active_since < older_than,
                )
            )
        ).scalars()
        return [to_domain(row, Conversation) for row in rows]


class VisitorNumberRepository(_Repository, AbstractVisitorNumberRepository):
    async def next(self, binding_id: UUID) -> int:
        statement = pg_insert(VisitorNumberCounterRow).values(binding_id=binding_id, last_number=1)
        result = await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["binding_id"],
                set_={"last_number": VisitorNumberCounterRow.last_number + 1},
            ).returning(VisitorNumberCounterRow.last_number)
        )
        return result.scalar_one()


class OperatorProfileRepository(_Repository, AbstractOperatorProfileRepository):
    async def remember(
        self, org_id: int, user_id: int, display_name: str | None, now: datetime
    ) -> str | None:
        # Read first: the common case (the name did not change) then takes no row lock and writes nothing.
        stored = (
            await self._session.execute(
                select(OperatorProfileRow.display_name).where(
                    OperatorProfileRow.org_id == org_id, OperatorProfileRow.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if display_name is None or display_name == stored:
            return stored
        statement = pg_insert(OperatorProfileRow).values(
            org_id=org_id, user_id=user_id, display_name=display_name, updated_at=now
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["org_id", "user_id"],
                set_={
                    "display_name": statement.excluded.display_name,
                    "updated_at": statement.excluded.updated_at,
                },
            )
        )
        return display_name

    async def names(self, org_id: int, user_ids: Collection[int]) -> dict[int, str]:
        if not user_ids:
            return {}
        rows = await self._session.execute(
            select(OperatorProfileRow.user_id, OperatorProfileRow.display_name).where(
                OperatorProfileRow.org_id == org_id, OperatorProfileRow.user_id.in_(user_ids)
            )
        )
        return dict(rows.tuples().all())


def _violated_constraint(error: IntegrityError) -> str | None:
    return getattr(getattr(error.orig, "diag", None), "constraint_name", None)


class OperatorAliasRepository(_Repository, AbstractOperatorAliasRepository):
    async def get(self, binding_id: UUID, user_id: int) -> str | None:
        return (
            await self._session.execute(
                select(OperatorAliasRow.alias).where(
                    OperatorAliasRow.binding_id == binding_id, OperatorAliasRow.user_id == user_id
                )
            )
        ).scalar_one_or_none()

    async def set(self, binding_id: UUID, user_id: int, alias: str, now: datetime) -> None:
        statement = pg_insert(OperatorAliasRow).values(
            binding_id=binding_id,
            user_id=user_id,
            alias=alias,
            alias_key=public_name_key(alias),
            updated_at=now,
        )
        try:
            # A savepoint takes a refused claim, so the caller's transaction is not aborted.
            async with self._session.begin_nested():
                await self._session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["binding_id", "user_id"],
                        set_={
                            "alias": statement.excluded.alias,
                            "alias_key": statement.excluded.alias_key,
                            "updated_at": statement.excluded.updated_at,
                        },
                    )
                )
        except IntegrityError as error:
            if _violated_constraint(error) == "uq_operator_alias_binding_alias":
                raise AliasTakenError() from error
            raise

    async def clear(self, binding_id: UUID, user_id: int) -> None:
        await self._session.execute(
            delete(OperatorAliasRow).where(
                OperatorAliasRow.binding_id == binding_id, OperatorAliasRow.user_id == user_id
            )
        )

    async def is_taken(self, binding_id: UUID, alias_key: str) -> bool:
        found = await self._session.execute(
            select(OperatorAliasRow.user_id)
            .where(
                OperatorAliasRow.binding_id == binding_id, OperatorAliasRow.alias_key == alias_key
            )
            .limit(1)
        )
        return found.scalar_one_or_none() is not None

    async def mine(self, org_id: int, user_id: int) -> list[tuple[UUID, str]]:
        rows = await self._session.execute(
            select(OperatorAliasRow.binding_id, OperatorAliasRow.alias)
            .join(BindingRow, BindingRow.id == OperatorAliasRow.binding_id)
            .where(BindingRow.org_id == org_id, OperatorAliasRow.user_id == user_id)
            .order_by(OperatorAliasRow.binding_id)
        )
        return list(rows.tuples().all())


class VisitorTokenRepository(_Repository, AbstractVisitorTokenRepository):
    async def add(self, token: VisitorToken) -> None:
        self._session.add(to_row(token, VisitorTokenRow))
        await self._session.flush()

    async def get(self, token_hash: str) -> VisitorToken | None:
        row = await self._session.get(VisitorTokenRow, token_hash)
        return to_domain(row, VisitorToken) if row else None

    async def touch(self, token_hash: str, now: datetime) -> None:
        await self._session.execute(
            update(VisitorTokenRow)
            .where(VisitorTokenRow.token_hash == token_hash)
            .values(last_used_at=now)
        )

    async def delete_for_binding(self, binding_id: UUID) -> int:
        result = await self._session.execute(
            delete(VisitorTokenRow).where(
                VisitorTokenRow.conversation_id.in_(
                    select(ConversationRow.id).where(ConversationRow.binding_id == binding_id)
                )
            )
        )
        return result.rowcount

    async def delete_idle(self, used_before: datetime) -> int:
        result = await self._session.execute(
            delete(VisitorTokenRow).where(VisitorTokenRow.last_used_at < used_before)
        )
        return result.rowcount


class MessageRepository(_Repository, AbstractMessageRepository):
    async def add(self, message: Message) -> None:
        self._session.add(to_row(message, MessageRow))
        await self._session.flush()

    async def set_session(self, message_id: UUID, session_id: int) -> None:
        await self._session.execute(
            update(MessageRow).where(MessageRow.id == message_id).values(session_id=session_id)
        )

    async def page(self, conversation_id: UUID, before: UUID | None, limit: int) -> list[Message]:
        query = select(MessageRow).where(MessageRow.conversation_id == conversation_id)
        if before is not None:
            query = query.where(MessageRow.id < before)
        rows = (
            (await self._session.execute(query.order_by(MessageRow.id.desc()).limit(limit)))
            .scalars()
            .all()
        )
        return [to_domain(row, Message) for row in reversed(rows)]

    async def history(self, conversation_id: UUID, window: int) -> list[dict]:
        rows = (
            await self._session.execute(
                select(MessageRow.role, MessageRow.content, MessageRow.action)
                .where(
                    MessageRow.conversation_id == conversation_id,
                    MessageRow.role.in_(HISTORY_ROLES),
                )
                .order_by(MessageRow.id.desc())
                .limit(window)
            )
        ).all()
        return [
            {
                "role": role,
                "content": content,
                **({"action": _history_action(action)} if action is not None else {}),
            }
            for role, content, action in reversed(rows)
        ]


def _scope(stream: Stream, conversation_id: UUID | None, org_id: int | None) -> list:
    conditions = [ConversationEventRow.stream == stream.value]
    if conversation_id is not None:
        conditions.append(ConversationEventRow.conversation_id == conversation_id)
    if org_id is not None:
        conditions.append(ConversationEventRow.org_id == org_id)
    return conditions


class EventRepository(_Repository, AbstractEventRepository):
    async def add(self, event: ConversationEvent) -> int:
        result = await self._session.execute(
            insert(ConversationEventRow)
            .values(**values_of(event, exclude=("seq",)))
            .returning(ConversationEventRow.seq)
        )
        event.seq = result.scalar_one()
        return event.seq

    async def replay(
        self,
        stream: Stream,
        *,
        conversation_id: UUID | None = None,
        org_id: int | None = None,
        after_seq: int | None,
    ) -> list[ConversationEvent]:
        conditions = _scope(stream, conversation_id, org_id)
        if after_seq is not None:
            conditions.append(ConversationEventRow.seq > after_seq)
        rows = (
            await self._session.execute(
                select(ConversationEventRow).where(*conditions).order_by(ConversationEventRow.seq)
            )
        ).scalars()
        return [to_domain(row, ConversationEvent) for row in rows]

    async def min_seq(
        self, stream: Stream, *, conversation_id: UUID | None = None, org_id: int | None = None
    ) -> int:
        return (
            await self._session.execute(
                select(func.coalesce(func.min(ConversationEventRow.seq), 0)).where(
                    *_scope(stream, conversation_id, org_id)
                )
            )
        ).scalar_one()

    async def max_seq(
        self, stream: Stream, *, conversation_id: UUID | None = None, org_id: int | None = None
    ) -> int:
        return (
            await self._session.execute(
                select(func.coalesce(func.max(ConversationEventRow.seq), 0)).where(
                    *_scope(stream, conversation_id, org_id)
                )
            )
        ).scalar_one()

    async def delete_older_than(self, cutoff: datetime) -> int:
        result = await self._session.execute(
            delete(ConversationEventRow).where(ConversationEventRow.created_at < cutoff)
        )
        return result.rowcount


class UsageRepository(_Repository, AbstractUsageRepository):
    async def add_daily(self, binding_id: UUID, day: date, tokens: int) -> None:
        statement = pg_insert(DailyUsageRow).values(binding_id=binding_id, day=day, tokens=tokens)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["binding_id", "day"],
                set_={"tokens": DailyUsageRow.tokens + statement.excluded.tokens},
            )
        )

    async def daily_tokens(self, binding_id: UUID, day: date) -> int:
        value = (
            await self._session.execute(
                select(DailyUsageRow.tokens).where(
                    DailyUsageRow.binding_id == binding_id, DailyUsageRow.day == day
                )
            )
        ).scalar_one_or_none()
        return int(value or 0)


class ReceiptRepository(_Repository, AbstractReceiptRepository):
    async def add(self, receipt: CallbackReceipt) -> None:
        self._session.add(to_row(receipt, CallbackReceiptRow))
        await self._session.flush()

    async def get(self, run_id: UUID) -> CallbackReceipt | None:
        row = await self._session.get(CallbackReceiptRow, run_id)
        return to_domain(row, CallbackReceipt) if row else None

    async def bind_session(self, run_id: UUID, session_id: int) -> bool:
        result = await self._session.execute(
            update(CallbackReceiptRow)
            .where(
                CallbackReceiptRow.run_id == run_id,
                or_(
                    CallbackReceiptRow.session_id.is_(None),
                    CallbackReceiptRow.session_id == session_id,
                ),
            )
            .values(session_id=session_id)
            .returning(CallbackReceiptRow.run_id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_received(
        self, run_id: UUID, tokens_counted: int = 0, *, keep_secret: bool = False
    ) -> bool:
        values = {"received_at": utcnow(), "tokens_counted": tokens_counted}
        if not keep_secret:
            values["secret"] = ""
        result = await self._session.execute(
            update(CallbackReceiptRow)
            .where(
                CallbackReceiptRow.run_id == run_id,
                CallbackReceiptRow.received_at.is_(None),
            )
            .values(**values)
            .returning(CallbackReceiptRow.run_id)
        )
        return result.scalar_one_or_none() is not None

    async def raise_tokens_counted(self, run_id: UUID, tokens: int) -> int:
        counted = (
            await self._session.execute(
                select(CallbackReceiptRow.tokens_counted).where(
                    CallbackReceiptRow.run_id == run_id,
                    CallbackReceiptRow.received_at.is_not(None),
                )
            )
        ).scalar_one_or_none()
        if counted is None:
            return 0
        await self._session.execute(
            update(CallbackReceiptRow)
            .where(CallbackReceiptRow.run_id == run_id)
            .values(secret="", tokens_counted=max(counted, tokens))
        )
        return max(0, tokens - counted)

    async def delete_older_than(self, cutoff: datetime) -> int:
        result = await self._session.execute(
            delete(CallbackReceiptRow).where(
                func.coalesce(CallbackReceiptRow.received_at, CallbackReceiptRow.created_at)
                < cutoff
            )
        )
        return result.rowcount
