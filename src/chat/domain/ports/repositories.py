from __future__ import (
    annotations,  # a `list` method in the class body shadows the builtin in later annotations
)

import abc
from collections.abc import Collection
from datetime import date, datetime
from uuid import UUID

from domain.enums import InboxOrder, InboxSection, Mode, Stream
from domain.models import (
    Binding,
    CallbackReceipt,
    Conversation,
    ConversationEvent,
    InboxBadge,
    Message,
    VisitorToken,
)
from domain.search import InboxSearch


class AbstractBindingRepository(abc.ABC):
    @abc.abstractmethod
    async def add(self, binding: Binding) -> None: ...

    @abc.abstractmethod
    async def get_with_operator_alias(
        self, binding_id: UUID, user_id: int
    ) -> tuple[Binding, str | None] | None:
        """The binding and the operator's alias on it (None without one), in one read."""

    @abc.abstractmethod
    async def get(
        self,
        binding_id: UUID,
        org_id: int | None = None,
        *,
        for_update: bool = False,
        for_share: bool = False,
    ) -> Binding | None:
        """By id; with `org_id` the binding must belong to that org (None otherwise).

        `for_update` locks the row. `for_share` holds a shared row lock instead, so a delete,
        rotation or identity switch waits for this transaction.
        """

    @abc.abstractmethod
    async def get_by_public_key(
        self, public_key: str, *, for_share: bool = False
    ) -> Binding | None:
        """`for_share` holds a shared row lock, so a rotation or an identity switch waits for this transaction."""

    @abc.abstractmethod
    async def list(self, org_id: int) -> list[Binding]: ...

    @abc.abstractmethod
    async def update(self, binding: Binding) -> None: ...

    @abc.abstractmethod
    async def set_broken_reason(self, binding_id: UUID, reason: str | None) -> None:
        """Write only `broken_reason` (and `updated_at`), so a concurrent edit of other columns survives."""

    @abc.abstractmethod
    async def delete(self, binding_id: UUID, org_id: int) -> bool: ...


class AbstractConversationRepository(abc.ABC):
    @abc.abstractmethod
    async def add(self, conversation: Conversation) -> None: ...

    @abc.abstractmethod
    async def get(
        self,
        conversation_id: UUID,
        org_id: int | None = None,
        *,
        for_update: bool = False,
        skip_locked: bool = False,
    ) -> Conversation | None:
        """`for_update` locks the row until commit; use it whenever the read is followed by `update()`.

        `skip_locked` (with `for_update`) answers None at once when another transaction holds
        the row, instead of waiting for it.
        """

    @abc.abstractmethod
    async def get_open_by_subject(
        self, binding_id: UUID, subject: str, *, for_update: bool = False
    ) -> Conversation | None:
        """The subject's open conversation on the binding; a subject has at most one."""

    @abc.abstractmethod
    async def claim_run_slot(self, conversation_id: UUID) -> bool:
        """`idle` → `starting` in one conditional update; False when a run is already in flight
        or the conversation is closed."""

    @abc.abstractmethod
    async def update(self, conversation: Conversation) -> None: ...

    @abc.abstractmethod
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
        """One inbox section in keyset order, narrowed by `mode`, `holder_id` and `search`.

        Waiting, In progress, Bot, Test and Closed never share a row; tests are only in Test
        (see `InboxSection`). Waiting: a visitor waits for a person, longest wait first (a
        queue). In progress: open, held, nobody waiting, at least one message. Bot: open, in bot
        mode with at least one message. Test: test conversations with at least one message,
        whatever their state, closed ones included. Closed: closed with at least one message,
        most recently closed first. Human (kept for older clients): every open handed-off
        conversation, first handed off first; it overlaps Waiting and In progress. Silent
        conversations are listed only in Waiting and Human.

        Args:
            after: Keyset `(at, id)` of the last row already seen, `at` being the section's
                `key_field`; only rows strictly after it in the section's order are returned.
                `org_id` still applies, so a key taken from another organization's row leaks
                nothing.
            order: Newest or oldest activity first; Waiting, Human and Closed ignore it.
            holder_id: Only conversations this operator holds. Bot rows have no holder, so Bot
                answers no rows without a query.
            search: Only conversations it matches (see `InboxSearch`).
        """

    @abc.abstractmethod
    async def badges(self, org_id: int) -> list[InboxBadge]:
        """Every conversation in the org's Waiting section, tests excluded, in no particular order.

        Waiting only: it is the demand still open, and a closed conversation never waits. In
        progress holds answered conversations until someone releases or closes them, or a
        Support desk's close-after timer does, so it is no demand to count.
        """

    @abc.abstractmethod
    async def unanswered_past_response_time(self, now: datetime, limit: int) -> list[UUID]:
        """Up to `limit` conversations whose visitor has waited past the desk's response time on
        a desk that hands back then, earliest deadline first. Tests are excluded.

        Candidates only: read without a lock, so the caller re-checks each under its own. It sets
        planner settings with SET LOCAL, which hold until the transaction ends: call it in a unit
        of work of its own (as the reconcile loop does), never inside a larger transaction.
        """

    @abc.abstractmethod
    async def inactive_past_close_after(self, now: datetime, limit: int) -> list[UUID]:
        """Up to `limit` open conversations on Support desks silent past the desk's close-after
        time, with no run in flight, earliest deadline first. Tests and silent conversations
        are excluded.

        Candidates only: read without a lock, so the caller re-checks each under its own. It sets
        planner settings with SET LOCAL, which hold until the transaction ends: call it in a unit
        of work of its own (as the reconcile loop does), never inside a larger transaction.
        """

    @abc.abstractmethod
    async def stale_runs(self, older_than: datetime) -> list[tuple[Conversation, int]]:
        """`running` conversations whose `active_since` is before `older_than`, with the run's session id."""

    @abc.abstractmethod
    async def unconfirmed_starts(self, older_than: datetime) -> list[Conversation]:
        """`starting` conversations whose `active_since` is before `older_than`.

        `starting` lasts while Django is asked for the run, and stays when that call timed out
        without telling whether the run was created.
        """

    @abc.abstractmethod
    async def delete_inactive_batch(self, org_id: int, cutoff: datetime, limit: int) -> int:
        """Delete up to `limit` of the org's closed conversations last active before `cutoff`,
        oldest first, and return how many went. Their messages, events, visitor tokens and callback receipts
        go with them (ON DELETE CASCADE). The caller commits; fewer than `limit` means none is
        left that this call could take.

        Last active is the last message, or the creation when there is none. Open conversations
        are never deleted, and neither is a closed one whose run's callback is still owed (a
        receipt that keeps its secret). Rows are locked FOR UPDATE SKIP LOCKED: a row another
        transaction holds is skipped, not waited for. On a row such a transaction changed and
        committed meanwhile, the conversation's own columns are checked again under the row
        lock; the receipt test (NOT EXISTS) uses the statement's snapshot.
        """


class AbstractVisitorNumberRepository(abc.ABC):
    @abc.abstractmethod
    async def next(self, binding_id: UUID) -> int:
        """The binding's next visitor number, 1 for its first conversation.

        Call it in the transaction that creates the conversation. The counter row stays locked
        until that transaction ends, so concurrent creates on one binding take consecutive
        numbers, and a create that rolls back gives its number back.
        """


class AbstractOperatorProfileRepository(abc.ABC):
    """Operators' display names, kept per org: no read ever crosses into another org."""

    @abc.abstractmethod
    async def remember(
        self, org_id: int, user_id: int, display_name: str | None, now: datetime
    ) -> str | None:
        """Store the operator's display name in the org when it differs from the stored one; return the name on record there.

        An unchanged name writes nothing. None (EpicStaff sent no name) keeps the stored one.
        """

    @abc.abstractmethod
    async def names(self, org_id: int, user_ids: Collection[int]) -> dict[int, str]:
        """Display names in the org by user id; an id never remembered there is absent. No query for no ids."""


class AbstractOperatorAliasRepository(abc.ABC):
    """Each operator's name on each desk, shown to visitors. Callers check the desk is in the
    caller's org first: the rows themselves carry no org."""

    @abc.abstractmethod
    async def get(self, binding_id: UUID, user_id: int) -> str | None: ...

    @abc.abstractmethod
    async def set(self, binding_id: UUID, user_id: int, alias: str, now: datetime) -> None:
        """Make `alias` the operator's name on the desk, replacing theirs (a change of case too).

        Raises:
            AliasTakenError: Another operator on the desk has it, in any case. The unique index
                alone decides, so of two concurrent claims the second fails once the first
                commits. The caller's transaction stays usable.
        """

    @abc.abstractmethod
    async def clear(self, binding_id: UUID, user_id: int) -> None: ...

    @abc.abstractmethod
    async def is_taken(self, binding_id: UUID, alias_key: str) -> bool:
        """Whether an operator on the desk uses an alias with this `public_name_key`."""

    @abc.abstractmethod
    async def mine(self, org_id: int, user_id: int) -> list[tuple[UUID, str]]:
        """The operator's `(desk id, alias)` pairs on the org's desks, by desk id."""


class AbstractVisitorTokenRepository(abc.ABC):
    @abc.abstractmethod
    async def add(self, token: VisitorToken) -> None: ...

    @abc.abstractmethod
    async def get(self, token_hash: str) -> VisitorToken | None: ...

    @abc.abstractmethod
    async def touch(self, token_hash: str, now: datetime) -> None:
        """Set `last_used_at`; the idle expiry slides from here."""

    @abc.abstractmethod
    async def delete_for_binding(self, binding_id: UUID) -> int:
        """Revoke every visitor token of the binding's conversations, in one statement."""

    @abc.abstractmethod
    async def delete_idle(self, used_before: datetime) -> int:
        """Prune tokens not used since `used_before`; they are already rejected."""


class AbstractMessageRepository(abc.ABC):
    @abc.abstractmethod
    async def add(self, message: Message) -> None: ...

    @abc.abstractmethod
    async def set_session(self, message_id: UUID, session_id: int) -> None: ...

    @abc.abstractmethod
    async def page(self, conversation_id: UUID, before: UUID | None, limit: int) -> list[Message]:
        """The newest `limit` messages (older than `before` when given), oldest first."""

    @abc.abstractmethod
    async def history(self, conversation_id: UUID, window: int) -> list[dict]:
        """The last `window` user/assistant/operator messages as `[{role, content}]`, oldest first."""


class AbstractEventRepository(abc.ABC):
    @abc.abstractmethod
    async def add(self, event: ConversationEvent) -> int:
        """Insert and return the assigned `seq`."""

    @abc.abstractmethod
    async def replay(
        self,
        stream: Stream,
        *,
        conversation_id: UUID | None = None,
        org_id: int | None = None,
        after_seq: int | None,
    ) -> list[ConversationEvent]: ...

    @abc.abstractmethod
    async def min_seq(
        self, stream: Stream, *, conversation_id: UUID | None = None, org_id: int | None = None
    ) -> int:
        """Lowest `seq` in the scope `replay` reads, or 0 when it has no rows."""

    @abc.abstractmethod
    async def max_seq(
        self, stream: Stream, *, conversation_id: UUID | None = None, org_id: int | None = None
    ) -> int:
        """Highest `seq` in the scope `replay` reads, or 0 when it has no rows."""

    @abc.abstractmethod
    async def delete_older_than(self, cutoff: datetime) -> int: ...


class AbstractUsageRepository(abc.ABC):
    @abc.abstractmethod
    async def add_daily(self, binding_id: UUID, day: date, tokens: int) -> None: ...

    @abc.abstractmethod
    async def daily_tokens(self, binding_id: UUID, day: date) -> int: ...


class AbstractReceiptRepository(abc.ABC):
    @abc.abstractmethod
    async def add(self, receipt: CallbackReceipt) -> None: ...

    @abc.abstractmethod
    async def get(self, run_id: UUID) -> CallbackReceipt | None: ...

    @abc.abstractmethod
    async def bind_session(self, run_id: UUID, session_id: int) -> bool:
        """Record Django's session id for the run; False when it is already bound to another one."""

    @abc.abstractmethod
    async def mark_received(
        self, run_id: UUID, tokens_counted: int = 0, *, keep_secret: bool = False
    ) -> bool:
        """Set `received_at` and `tokens_counted`; False when already received or unknown.

        Args:
            keep_secret: Keep verifying callbacks for the run, because the usage applied was not
                Django's final one. Otherwise the secret is cleared.
        """

    @abc.abstractmethod
    async def raise_tokens_counted(self, run_id: UUID, tokens: int) -> int:
        """For a received run: clear the secret, raise `tokens_counted` to `tokens`, return the increase (0 if none).

        The caller holds the conversation lock, which serializes every writer of the receipt.
        """

    @abc.abstractmethod
    async def delete_older_than(self, cutoff: datetime) -> int:
        """Drop receipts received, or created and never received, before `cutoff`.

        Django stops retrying a callback after 24 h, so such a receipt guards nothing.
        """
