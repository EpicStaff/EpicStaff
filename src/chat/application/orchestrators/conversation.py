import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from common.humanize import Rate
from common.utils import client_network, new_id, utc_today, utcnow
from domain.enums import (
    CloseReason,
    IdentityMode,
    Mode,
    OnBudgetExhausted,
    Role,
    RunState,
    SubmitState,
)
from domain.errors import (
    BindingBrokenError,
    BindingInactiveError,
    ConversationClosedError,
    FlowNotFoundError,
    FlowStartError,
    FlowUnavailableError,
    InvalidTokenError,
    MessageTooLongError,
    NotATestConversationError,
    NotFoundError,
    OriginNotAllowedError,
    RateLimitedError,
    RunInProgressError,
    SessionMismatchError,
    UpstreamUnavailableError,
)
from domain.models import Binding, CallbackReceipt, Conversation, Message, VisitorToken
from loguru import logger
from sqlalchemy.exc import IntegrityError

from application.orchestrators import budgets
from application.orchestrators.events import Emitter, store_message
from application.orchestrators.handoff import hand_off
from application.orchestrators.lifecycle import close_conversation, free_run_slot, stop_session
from application.ports import (
    AbstractFanout,
    AbstractFlowRunner,
    AbstractRateLimiter,
    AbstractUnitOfWork,
)
from application.results import ApplyOutcome, EndResult, SubmitResult
from application.tokens import (
    identity_subject,
    issue_visitor_token,
    new_callback_secret,
    visitor_token_hash,
)

__all__ = [
    "ApplyOutcome",
    "ConversationOrchestrator",
    "PublicLimits",
    "RunConfig",
    "SubmitResult",
    "parse_end_node_result",
]

IDENTITY_MAX_LIFETIME_SECONDS = 3600


@dataclass(frozen=True)
class RunConfig:
    # Django posts a run's result to `<callback_url>/<run id>`.
    callback_url: str
    ip_message_rate: Rate
    ip_conversation_rate: Rate


@dataclass(frozen=True)
class PublicLimits:
    """What a visitor message may carry beyond its desk's own limits: the deployment's, for every desk.

    The widget reads them from the conversation state; the public API enforces the byte limits
    on `action` and `chat_extra_data`.
    """

    action_max_bytes: int
    extra_data_max_bytes: int


def parse_end_node_result(result: object) -> EndResult:
    """Read the flow contract's outputs; anything malformed becomes "no reply"."""
    if not isinstance(result, dict):
        return EndResult(reply=None, actions=None, request_human=False)
    reply = result.get("reply")
    actions = result.get("actions")
    return EndResult(
        reply=reply if isinstance(reply, str) and reply.strip() else None,
        actions=actions if isinstance(actions, list) else None,
        request_human=result.get("request_human") is True,
    )


def run_variables(conversation: Conversation, history: list[dict], message: Message) -> dict:
    """The flow's start variables: the same six on every run, declared by the flow or not.

    A past action goes into `chat_history` cut down (`MessageRepository.history`); `action` is
    the current one, whole. The contract is documented in docs/chat/flow-contract.md.
    """
    return {
        "chat_history": history,
        "user_message": message.content,
        "action": message.action,
        "chat_extra_data": conversation.chat_extra_data,
        "chat_user_id": conversation.chat_user_id,
        "chat_conversation_id": str(conversation.id),
    }


def _stored_extra_data(chat_extra_data: dict) -> dict | None:
    """{} clears to no value: a null run variable replaces a default the flow declares, {} would merge into it."""
    return chat_extra_data or None


def _normalize_origin(origin: str | None) -> str:
    return (origin or "").strip().rstrip("/").lower()


# A token used again within this long keeps its stored `last_used_at`: no write on every request.
VISITOR_TOKEN_REFRESH = timedelta(hours=1)


def gate_active(binding: Binding, is_test: bool) -> None:
    """Inactive → 410, except for test conversations, so a flow can be tried before it goes live."""
    if not binding.is_active and not is_test:
        raise BindingInactiveError()


def gate(binding: Binding, origin: str | None, is_test: bool) -> None:
    """Lifecycle step 2: inactive → 410, broken → 503, origin not allowed → 403.

    Test conversations skip the active and origin checks, so a flow can be tried before it goes live.
    """
    gate_active(binding, is_test)
    if binding.broken_reason:
        raise BindingBrokenError()  # the stored reason is for operators, not visitors
    if is_test:
        return
    allowed = {_normalize_origin(item) for item in binding.allowed_origins}
    normalized = _normalize_origin(origin)
    if not normalized or normalized not in allowed:
        raise OriginNotAllowedError()


def _total_tokens(session_id: int, token_usage: dict | None) -> int:
    value = (token_usage or {}).get("total_tokens") or 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        logger.warning(
            "Session {} reported non-integer total_tokens {!r}; counted as 0", session_id, value
        )
        return 0


class ConversationOrchestrator:
    """Every public-side decision about a conversation, in the spec's lifecycle order."""

    def __init__(
        self,
        uow_factory: Callable[[], AbstractUnitOfWork],
        *,
        flows: AbstractFlowRunner,
        fanout: AbstractFanout,
        limiter: AbstractRateLimiter,
        config: RunConfig,
        visitor_token_idle_seconds: int,
    ):
        self._uow = uow_factory
        self._flows = flows
        self._fanout = fanout
        self._limiter = limiter
        self._config = config
        self._token_idle = timedelta(seconds=visitor_token_idle_seconds)
        # Refresh well inside the TTL, so a token in use never expires between two refreshes.
        self._token_refresh = min(VISITOR_TOKEN_REFRESH, self._token_idle / 2)

    # ---- creation and lookup -------------------------------------------------------------------

    async def create(
        self,
        public_key: str,
        identity_token: str | None,
        origin: str | None,
        client_ip: str,
        *,
        chat_extra_data: dict | None = None,
    ) -> tuple[Conversation, str, Binding]:
        """A widget's first call: find the binding by public key, mint a visitor token.

        `chat_extra_data` is stored on a new conversation; on a signed binding's existing one a
        non-null value replaces the stored one. {} stores no value.

        Returns:
            The conversation (on signed bindings the customer's open one, if any: a closed one
            is never resumed), a fresh visitor token, and the binding, whose display names the
            widget shows.
        """
        async with self._uow() as uow:
            # Shared lock until commit: a rotate-key or identity switch (FOR UPDATE) waits for this token,
            # then revokes it; a create behind a rotation re-reads the row, misses the old key and 404s.
            binding = await uow.bindings.get_by_public_key(public_key, for_share=True)
            if binding is None:
                raise NotFoundError("Unknown public key.")
            gate(binding, origin, is_test=False)
            limit, window = self._config.ip_conversation_rate
            retry_after = await self._limiter.hit(
                f"chat:rl:ipconv:{client_network(client_ip)}:{int(time.time() // window)}",
                limit,
                window,
            )
            if retry_after:
                raise RateLimitedError(retry_after)
            if binding.identity_mode == IdentityMode.SIGNED:
                subject = identity_subject(
                    identity_token,
                    binding.identity_secret or "",
                    now=int(time.time()),
                    max_lifetime_seconds=IDENTITY_MAX_LIFETIME_SECONDS,
                )
            else:
                subject = secrets.token_urlsafe(16)
            token, token_hash = issue_visitor_token()
            try:
                conversation = await self._bind_token(
                    uow, binding, subject, token_hash, chat_extra_data
                )
                await uow.commit()
            except IntegrityError as error:
                # Two devices of one signed subject raced to create its open conversation; join the winner's.
                await uow.rollback()
                # The rollback dropped the shared lock; a binding changed meanwhile issues no token.
                relocked = await uow.bindings.get_by_public_key(public_key, for_share=True)
                if relocked is None or relocked.identity_mode != binding.identity_mode:
                    raise NotFoundError("Unknown public key.") from error
                conversation = await self._bind_token(
                    uow, binding, subject, token_hash, chat_extra_data
                )
                await uow.commit()
        return conversation, token, binding

    async def _bind_token(
        self,
        uow: AbstractUnitOfWork,
        binding: Binding,
        subject: str,
        token_hash: str,
        chat_extra_data: dict | None,
    ) -> Conversation:
        """The subject's open conversation (created when it has none) plus one more device token for it."""
        replaces_extra_data = chat_extra_data is not None
        # Always locked: a lock waiting on a close re-checks `closed_at IS NULL` once the close
        # commits, so a device racing an end gets a new conversation, not the closed one.
        conversation = await uow.conversations.get_open_by_subject(
            binding.id, subject, for_update=True
        )
        if conversation is None:
            conversation = await self._add_conversation(
                uow,
                binding,
                subject,
                is_test=False,
                is_signed=binding.identity_mode == IdentityMode.SIGNED,
                chat_extra_data=_stored_extra_data(chat_extra_data),
            )
        elif replaces_extra_data:
            conversation.chat_extra_data = _stored_extra_data(chat_extra_data)
            await uow.conversations.update(conversation)
        await self._add_visitor_token(uow, conversation.id, token_hash)
        return conversation

    @staticmethod
    async def _add_visitor_token(
        uow: AbstractUnitOfWork, conversation_id: UUID, token_hash: str
    ) -> None:
        now = utcnow()
        await uow.visitor_tokens.add(VisitorToken(token_hash, conversation_id, now, now))

    async def create_test(self, binding_id: UUID, org_id: int) -> tuple[dict, str]:
        """An operator's simulate panel: a test conversation that skips the origin check.

        Returns:
            The conversation's inbox row, as `conversation.updated` carried it, and a visitor token.
        """
        async with self._uow() as uow:
            # Locked before the counter row, as `create` does: a desk delete then waits here, rather
            # than holding the binding while its cascade waits for the counter row this create holds.
            binding = await uow.bindings.get(binding_id, org_id=org_id, for_share=True)
            if binding is None:
                raise NotFoundError()
            token, token_hash = issue_visitor_token()
            conversation = await self._add_conversation(
                uow, binding, f"test-{secrets.token_urlsafe(8)}", is_test=True
            )
            await self._add_visitor_token(uow, conversation.id, token_hash)
            emitter = Emitter(uow, self._fanout)
            row = await emitter.conversation_updated(conversation)
            await uow.commit()
            await emitter.flush()
        return row, token

    async def issue_test_visitor_token(self, conversation_id: UUID, org_id: int) -> str:
        """One more visitor token for an operator's test conversation; earlier tokens stay valid.

        The server keeps only token hashes, so this is how an operator writes as the visitor
        again after the page that held the first token is gone.

        Raises:
            NotFoundError: No such conversation in `org_id`.
            NotATestConversationError: A real visitor's conversation: operators never get its token.
        """
        async with self._uow() as uow:
            conversation = await uow.conversations.get(conversation_id, org_id=org_id)
            if conversation is None:
                raise NotFoundError()
            if not conversation.is_test:
                raise NotATestConversationError()
            token, token_hash = issue_visitor_token()
            await self._add_visitor_token(uow, conversation.id, token_hash)
            await uow.commit()
        return token

    @staticmethod
    async def _add_conversation(
        uow: AbstractUnitOfWork,
        binding: Binding,
        subject: str,
        *,
        is_test: bool,
        is_signed: bool = False,
        chat_extra_data: dict | None = None,
    ) -> Conversation:
        """Insert a new conversation, numbered in this transaction: a rollback gives the number back.

        The caller holds a shared lock on the binding: the counter row comes second, after the
        binding, on every path, so a binding delete (binding, then counter) cannot deadlock it.
        """
        conversation = Conversation(
            id=new_id(),
            binding_id=binding.id,
            org_id=binding.org_id,
            subject=subject,
            visitor_number=await uow.visitor_numbers.next(binding.id),
            is_test=is_test,
            mode=Mode.BOT,
            assigned_operator_id=None,
            run_state=RunState.IDLE,
            active_run_id=None,
            active_since=None,
            tokens_used=0,
            turns=0,
            usage_day=utc_today(),
            tokens_today=0,
            turns_today=0,
            last_message_at=None,
            last_message_preview="",
            handoff_reason="",
            created_at=utcnow(),
            chat_extra_data=chat_extra_data,
            is_signed=is_signed,
        )
        await uow.conversations.add(conversation)
        return conversation

    async def _resolve(
        self,
        uow: AbstractUnitOfWork,
        conversation_id: UUID,
        visitor_token: str | None,
        *,
        for_update: bool = False,
    ) -> Conversation:
        if not visitor_token:
            raise InvalidTokenError()
        token = await uow.visitor_tokens.get(visitor_token_hash(visitor_token))
        now = utcnow()
        # An idle-expired token answers exactly like an unknown one.
        if token is None or token.last_used_at < now - self._token_idle:
            raise InvalidTokenError()
        if token.conversation_id != conversation_id:
            raise NotFoundError()
        conversation = await uow.conversations.get(token.conversation_id, for_update=for_update)
        if conversation is None:  # deleted between the token lookup and the read
            raise NotFoundError()
        # After the conversation read: the conversation lock comes first, as on every write path.
        if token.last_used_at < now - self._token_refresh:
            await uow.visitor_tokens.touch(token.token_hash, now)
        return conversation

    async def resolve(
        self, conversation_id: UUID, visitor_token: str | None
    ) -> tuple[Conversation, Binding]:
        """For the visitor's reads: unknown or idle-expired token → 401, another conversation's → 404,
        inactive binding → 410 (test conversations excepted). Commits the token's refresh.

        Returns:
            The conversation and its binding, read in the same transaction.
        """
        async with self._uow() as uow:
            conversation = await self._resolve(uow, conversation_id, visitor_token)
            binding = await uow.bindings.get(conversation.binding_id)
            if binding is None:  # deleted after the unlocked conversation read
                raise NotFoundError()
            gate_active(binding, conversation.is_test)
            await uow.commit()
        return conversation, binding

    async def check_streamable(self, conversation_id: UUID) -> None:
        """At stream connect: the ticket was issued up to a ticket TTL ago, so re-check the binding."""
        async with self._uow() as uow:
            conversation = await uow.conversations.get(conversation_id)
            binding = await uow.bindings.get(conversation.binding_id) if conversation else None
            if binding is None:
                raise NotFoundError()
            gate_active(binding, conversation.is_test)

    async def messages(
        self, conversation_id: UUID, before: UUID | None, limit: int
    ) -> list[Message]:
        async with self._uow() as uow:
            return await uow.messages.page(conversation_id, before, limit)

    async def end(
        self, conversation_id: UUID, visitor_token: str | None, origin: str | None
    ) -> tuple[Conversation, Binding]:
        """The visitor's "Start a new chat": close the conversation (reason `ended`).

        Checked like a message: the visitor token, then the binding's gate (inactive → 410,
        broken → 503, origin → 403). Idempotent: a conversation already closed, for any reason,
        is answered as it is. A run in flight is stopped; its late callback only counts tokens.
        The visitor's tokens stay valid, so the history can still be read.

        Returns:
            The conversation and its binding, read in the same transaction.
        """
        async with self._uow() as uow:
            conversation = await self._resolve(uow, conversation_id, visitor_token, for_update=True)
            binding = await uow.bindings.get(conversation.binding_id)
            gate(binding, origin, conversation.is_test)
            if not conversation.is_open:
                await uow.commit()
                return conversation, binding
            emitter = Emitter(uow, self._fanout)
            _, session_to_stop = await close_conversation(
                uow, emitter, conversation, CloseReason.ENDED, utcnow()
            )
            await uow.conversations.update(conversation)
            await uow.commit()
            await emitter.flush()
        await stop_session(self._flows, session_to_stop)
        return conversation, binding

    async def stop(
        self, conversation_id: UUID, visitor_token: str | None, origin: str | None
    ) -> tuple[Conversation, Binding]:
        """The visitor's Stop: end the run in flight; the conversation stays open, with the bot.

        The slot is freed here, as a take over frees it, and Django is asked to stop the run
        after commit. Waiting for the run's own `stop` result instead would make
        `apply_run_result` post "The flow stopped with status stop." and hand off to a person,
        which is right for a run that fails, not for the visitor's own stop: so nothing is
        posted and nobody is asked for. The run's late callback finds the slot gone and only
        counts its tokens. A run still starting is stopped by its `submit` once Django answers.

        Checked like `end`: the visitor token, then the binding's gate. Idempotent: with no run
        in flight, on a closed conversation or outside bot mode the state is answered as it is.

        Returns:
            The conversation and its binding, read in the same transaction.
        """
        async with self._uow() as uow:
            conversation = await self._resolve(uow, conversation_id, visitor_token, for_update=True)
            binding = await uow.bindings.get(conversation.binding_id)
            gate(binding, origin, conversation.is_test)
            emitter = Emitter(uow, self._fanout)
            session_to_stop = None
            if (
                conversation.is_open
                and conversation.mode == Mode.BOT
                and conversation.run_state != RunState.IDLE
            ):
                _, session_to_stop = await free_run_slot(uow, conversation)
                await emitter.conversation(conversation, "run.finished", {"status": "stop"})
                await emitter.conversation_updated(conversation)
                await uow.conversations.update(conversation)
            await uow.commit()
            await emitter.flush()
        await stop_session(self._flows, session_to_stop)
        return conversation, binding

    # ---- inbound message -----------------------------------------------------------------------

    async def submit(
        self,
        conversation_id: UUID,
        visitor_token: str | None,
        content: str,
        origin: str | None,
        client_ip: str,
        *,
        action: dict | None = None,
        chat_extra_data: dict | None = None,
    ) -> SubmitResult:
        """Lifecycle steps 1-9. Nothing is stored before the conversation may take the message.

        An action reply may have no content. `chat_extra_data` replaces the stored value only
        once the message is stored; a refused request leaves it unchanged.

        Returns:
            The stored message id and one of processing / forwarded_to_operator /
            budget_exhausted / stopped (the visitor stopped the run before it started, or while
            it was starting: the message is stored, no run answers it).
            A start Django did not answer (timeout, connection error) is processing too: its
            callback or the reconciler settles it.

        Raises:
            ConversationClosedError: Closed before the message was stored, which then stores
                nothing; or closed while its run was starting, which keeps the message and
                stops the run.
            FlowUnavailableError: The reconciler released the run slot before the message was
                stored (the start was taken for lost); nothing is stored.
        """
        async with self._uow() as uow:
            conversation = await self._resolve(uow, conversation_id, visitor_token, for_update=True)
            binding = await uow.bindings.get(conversation.binding_id)
            gate(binding, origin, conversation.is_test)
            # Before the content checks and the rate limits: a closed conversation counts nothing.
            conversation.ensure_open()
            if not content.strip():
                if action is None:
                    raise MessageTooLongError()
                content = ""
            if len(content) > binding.max_message_length:
                raise MessageTooLongError()
            await self._rate_limit(conversation, binding, client_ip)
            if conversation.mode != Mode.BOT:
                return await self._forward_to_operator(
                    uow, conversation, content, action, chat_extra_data
                )
            if not await uow.conversations.claim_run_slot(conversation.id):
                raise RunInProgressError()
            last_message_at = conversation.last_message_at
            await uow.commit()

        # The slot is ours from here, unless something took it between the transactions: every
        # exit below releases it, and so do a take over, a stop, a close and the reconciler.
        async with self._uow() as uow:
            conversation = await uow.conversations.get(conversation_id, for_update=True)
            # Closed meanwhile: the close freed the slot.
            conversation.ensure_open()
            # Taken over or stopped (either, waiting on phase one's row lock, always lands here
            # first) or released by the reconciler: the slot is no longer as phase one left it.
            # Starting the run anyway would leave its id on an idle row, and its result would be
            # applied to a conversation an operator holds.
            if (
                conversation.run_state != RunState.STARTING
                or conversation.active_run_id is not None
            ):
                if conversation.mode != Mode.BOT:
                    return await self._forward_to_operator(
                        uow, conversation, content, action, chat_extra_data
                    )
                # The visitor's stop freed the slot and posted nothing; the reconciler's release
                # posts its notice, and names the run it may still hear from.
                if (
                    conversation.run_state == RunState.IDLE
                    and conversation.late_reply_run_id is None
                    and conversation.last_message_at == last_message_at
                ):
                    return await self._store_without_run(
                        uow, conversation, content, action, chat_extra_data, SubmitState.STOPPED
                    )
                raise FlowUnavailableError()
            # Handed off meanwhile with the slot left alone: the late reply of a run released
            # as unconfirmed asked for a human. The message is for a person now, not a run.
            if conversation.mode != Mode.BOT:
                self._release(conversation)
                return await self._forward_to_operator(
                    uow, conversation, content, action, chat_extra_data
                )
            emitter = Emitter(uow, self._fanout)
            today = utc_today()
            conversation.roll_usage_day(today)
            reason = budgets.exhausted_reason(
                binding, conversation, await uow.usage.daily_tokens(binding.id, today)
            )
            if reason:
                message = await self._store_user_message(
                    uow, emitter, conversation, content, action, chat_extra_data
                )
                self._release(conversation)
                handed_off = (
                    binding.on_budget_exhausted == OnBudgetExhausted.HANDOFF
                    and await hand_off(
                        emitter, conversation, binding, f"budget exhausted: {reason}"
                    )
                )
                if not handed_off:
                    await store_message(
                        uow, emitter, conversation, Role.ASSISTANT, binding.budget_exhausted_message
                    )
                await emitter.conversation_updated(conversation)
                await uow.conversations.update(conversation)
                await uow.commit()
                await emitter.flush()
                return SubmitResult(message.id, SubmitState.BUDGET_EXHAUSTED)
            history = await uow.messages.history(conversation.id, binding.history_window)
            message = await self._store_user_message(
                uow, emitter, conversation, content, action, chat_extra_data
            )
            variables = run_variables(conversation, history, message)
            # The receipt is stored with the message, before Django is asked: a callback that beats
            # the start response, or follows a lost one, still finds its run and secret.
            run_id, secret = new_id(), new_callback_secret()
            await uow.receipts.add(
                CallbackReceipt(
                    run_id=run_id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    secret=secret,
                    created_at=utcnow(),
                )
            )
            conversation.active_run_id = run_id
            conversation.late_reply_run_id = None
            await emitter.conversation_updated(conversation)
            await uow.conversations.update(conversation)
            await uow.commit()
            await emitter.flush()

        try:
            session_id = await self._flows.start_run(
                org_id=binding.org_id,
                graph_id=binding.graph_id,
                variables=variables,
                token_budget=budgets.run_token_budget(binding),
                callback_url=f"{self._config.callback_url.rstrip('/')}/{run_id}",
                callback_secret=secret,
            )
        except FlowNotFoundError as error:
            await self._fail_start(
                conversation_id,
                run_id,
                binding,
                "The flow behind this chat is gone.",
                broken="Django answered 404 for the flow.",
            )
            raise BindingBrokenError() from error
        except FlowStartError as error:
            logger.error("run-session failed for conversation {}: {}", conversation_id, error)
            await self._fail_start(
                conversation_id, run_id, binding, "The flow could not be started.", broken=None
            )
            raise FlowUnavailableError() from error
        except UpstreamUnavailableError as error:
            # Django may have started the run before the answer was lost. The conversation stays
            # `starting`: the run's callback settles it, or the reconciler releases the slot.
            logger.warning(
                "run-session outcome unknown for conversation {} (run {}): {}",
                conversation_id,
                run_id,
                error,
            )
            return SubmitResult(message.id, SubmitState.PROCESSING)

        async with self._uow() as uow:
            conversation = await uow.conversations.get(conversation_id, for_update=True)
            receipt = await uow.receipts.get(run_id)
            await self._bind_session(uow, receipt, session_id)
            if receipt.received_at is not None:
                # The callback beat this response and has already applied the run.
                await uow.commit()
                return SubmitResult(message.id, SubmitState.PROCESSING)
            # An operator claimed, the visitor stopped or someone closed while the run was
            # starting, or the reconciler already released the slot as unconfirmed: then the
            # run is not ours to keep.
            aborted = conversation.active_run_id != run_id or conversation.mode != Mode.BOT
            # Only the reconciler's release names the run as the one whose reply may come late.
            released_unconfirmed = conversation.late_reply_run_id == run_id
            emitter = Emitter(uow, self._fanout)
            if not aborted:
                conversation.run_state = RunState.RUNNING
                await emitter.conversation(conversation, "run.started", {})
                await emitter.conversation_updated(conversation)
                await uow.conversations.update(conversation)
            elif released_unconfirmed:
                # The visitor gets a 503 for this run below; its reply must not appear later.
                conversation.late_reply_run_id = None
                await uow.conversations.update(conversation)
            await uow.commit()
            await emitter.flush()
        if aborted:
            # The receipt stays live, so the stopped run's callback still counts its tokens.
            await stop_session(self._flows, session_id)
            conversation.ensure_open()
            if conversation.mode != Mode.BOT:
                return SubmitResult(message.id, SubmitState.FORWARDED_TO_OPERATOR)
            if released_unconfirmed:
                raise FlowUnavailableError()
            # Freed while starting with the bot still in charge: the visitor's stop (or a take
            # over already handed back). The message stays; no reply will come for it.
            return SubmitResult(message.id, SubmitState.STOPPED)
        return SubmitResult(message.id, SubmitState.PROCESSING)

    async def _forward_to_operator(
        self,
        uow: AbstractUnitOfWork,
        conversation: Conversation,
        content: str,
        action: dict | None,
        chat_extra_data: dict | None,
    ) -> SubmitResult:
        """Store the visitor's message for the person who has the conversation, and commit."""
        return await self._store_without_run(
            uow, conversation, content, action, chat_extra_data, SubmitState.FORWARDED_TO_OPERATOR
        )

    async def _store_without_run(
        self,
        uow: AbstractUnitOfWork,
        conversation: Conversation,
        content: str,
        action: dict | None,
        chat_extra_data: dict | None,
        state: SubmitState,
    ) -> SubmitResult:
        """Store the visitor's message with no run started for it, and commit."""
        emitter = Emitter(uow, self._fanout)
        message = await self._store_user_message(
            uow, emitter, conversation, content, action, chat_extra_data
        )
        await emitter.conversation_updated(conversation)
        await uow.conversations.update(conversation)
        await uow.commit()
        await emitter.flush()
        return SubmitResult(message.id, state)

    @staticmethod
    async def _store_user_message(
        uow: AbstractUnitOfWork,
        emitter: Emitter,
        conversation: Conversation,
        content: str,
        action: dict | None,
        chat_extra_data: dict | None,
    ) -> Message:
        # Replace, never merge: None keeps the stored value. The caller saves the conversation.
        if chat_extra_data is not None:
            conversation.chat_extra_data = _stored_extra_data(chat_extra_data)
        return await store_message(uow, emitter, conversation, Role.USER, content, action=action)

    async def _rate_limit(
        self, conversation: Conversation, binding: Binding, client_ip: str
    ) -> None:
        now = time.time()
        for prefix, (limit, window) in (
            (f"chat:rl:conv:{conversation.id}", Rate(binding.messages_per_minute, 60)),
            (f"chat:rl:ip:{client_network(client_ip)}", self._config.ip_message_rate),
        ):
            # Fixed windows: the bucket index in the key starts a fresh count each window.
            retry_after = await self._limiter.hit(f"{prefix}:{int(now // window)}", limit, window)
            if retry_after:
                raise RateLimitedError(retry_after)

    @staticmethod
    def _release(conversation: Conversation) -> None:
        conversation.run_state = RunState.IDLE
        conversation.active_run_id = None
        conversation.active_since = None

    @staticmethod
    async def _bind_session(
        uow: AbstractUnitOfWork, receipt: CallbackReceipt, session_id: int
    ) -> None:
        if not await uow.receipts.bind_session(receipt.run_id, session_id):
            logger.warning(
                "Run {} is bound to session {}, not {}; rejected",
                receipt.run_id,
                receipt.session_id,
                session_id,
            )
            raise SessionMismatchError()
        await uow.messages.set_session(receipt.message_id, session_id)

    async def _fail_start(
        self,
        conversation_id: UUID,
        run_id: UUID,
        binding: Binding,
        notice: str,
        *,
        broken: str | None,
    ) -> None:
        """Settle a run Django refused: post `notice` and free the slot, or, on a conversation
        closed meanwhile, which a close already settled, only retire the receipt.

        Raises:
            ConversationClosedError: Closed while the run was starting; the binding's broken
                reason is still recorded, since it describes the flow.
        """
        async with self._uow() as uow:
            conversation = await uow.conversations.get(conversation_id, for_update=True)
            # Django refused the run, so no callback will come; this also clears its secret.
            await uow.receipts.mark_received(run_id)
            if not conversation.is_open:
                if broken:
                    await uow.bindings.set_broken_reason(binding.id, broken)
                await uow.commit()
                raise ConversationClosedError(conversation.close_reason.value)
            emitter = Emitter(uow, self._fanout)
            await store_message(uow, emitter, conversation, Role.SYSTEM, notice)
            self._release(conversation)
            await emitter.conversation(conversation, "run.finished", {"status": "error"})
            await emitter.conversation_updated(conversation)
            await uow.conversations.update(conversation)
            if broken:
                await uow.bindings.set_broken_reason(binding.id, broken)
            await uow.commit()
            await emitter.flush()

    # ---- run result ----------------------------------------------------------------------------

    async def receipt(self, run_id: UUID) -> CallbackReceipt | None:
        """The run started here under this id; its secret is "" once applied or refused."""
        async with self._uow() as uow:
            return await uow.receipts.get(run_id)

    async def release_unconfirmed_start(self, conversation_id: UUID, run_id: UUID | None) -> bool:
        """Free a slot whose run Django never confirmed. False when the conversation moved on meanwhile.

        The receipt stays: if Django did start the run, its late callback still counts the tokens,
        and the conversation names the run as the one whose reply may still arrive late. Such a
        run is no longer watched by the reconciler, so CHAT_RUN_TIMEOUT does not stop it; crew's
        token budget and the manager's session TTL bound it.
        `run_id` is None when the service stopped between claiming the slot and storing the receipt.
        """
        async with self._uow() as uow:
            conversation = await uow.conversations.get(conversation_id, for_update=True)
            if conversation.run_state != RunState.STARTING or conversation.active_run_id != run_id:
                return False
            emitter = Emitter(uow, self._fanout)
            await store_message(
                uow, emitter, conversation, Role.SYSTEM, "The flow could not be started."
            )
            self._release(conversation)
            conversation.late_reply_run_id = run_id
            await emitter.conversation(conversation, "run.finished", {"status": "error"})
            await emitter.conversation_updated(conversation)
            await uow.conversations.update(conversation)
            await uow.commit()
            await emitter.flush()
        return True

    async def apply_run_result(
        self,
        run_id: UUID,
        session_id: int,
        status: str,
        end_node_result: object,
        token_usage: dict | None,
        *,
        final_usage: bool = True,
    ) -> ApplyOutcome:
        """Lifecycle step 10, from the callback or the reconcile loop. Idempotent per run.

        The run's tokens always count against the budgets. Its result is applied when the run
        still holds the slot, or when it ended with `end` and is the conversation's
        `late_reply_run_id` (released as an unconfirmed start, and the conversation has not
        moved on since): the reply then arrives late. Any other result is dropped, and so is
        every result on a closed conversation (closing frees the slot).

        Args:
            final_usage: False when `token_usage` is a snapshot (the reconcile loop): the receipt
                then keeps its secret, so Django's own callback can still add what the run used
                after the snapshot.

        Raises:
            SessionMismatchError: The run is already bound to another session id.
        """
        async with self._uow() as uow:
            receipt = await uow.receipts.get(run_id)
            if receipt is None:
                logger.info(
                    "Run {} (session {}) finished with {} but was never started here; ignored",
                    run_id,
                    session_id,
                    status,
                )
                return ApplyOutcome.IGNORED
            # The conversation lock comes first, as on every path that writes a receipt.
            conversation = await uow.conversations.get(receipt.conversation_id, for_update=True)
            await self._bind_session(uow, receipt, session_id)
            tokens = _total_tokens(session_id, token_usage)
            # A run started before midnight counts on the day it is applied, as in the binding's daily usage.
            today = utc_today()
            emitter = Emitter(uow, self._fanout)
            if not await uow.receipts.mark_received(run_id, tokens, keep_secret=not final_usage):
                extra = (
                    await uow.receipts.raise_tokens_counted(run_id, tokens) if final_usage else 0
                )
                if extra:
                    # A reconcile pass counted a snapshot; this is Django's final usage.
                    conversation.count_tokens(extra, today)
                    await uow.usage.add_daily(conversation.binding_id, today, extra)
                    await emitter.conversation_updated(conversation)
                    await uow.conversations.update(conversation)
                await uow.commit()
                await emitter.flush()
                return ApplyOutcome.DUPLICATE
            binding = await uow.bindings.get(conversation.binding_id)
            conversation.count_tokens(tokens, today)
            await uow.usage.add_daily(binding.id, today, tokens)
            holds_slot = conversation.active_run_id == run_id
            arrives_late = (
                not holds_slot
                and status == "end"
                and conversation.is_open
                and conversation.mode == Mode.BOT
                and conversation.late_reply_run_id == run_id
            )
            if arrives_late:
                conversation.late_reply_run_id = None
            if not holds_slot and not arrives_late:
                logger.warning(
                    "Run {} (session {}) finished with {} after conversation {} moved on; "
                    "{} tokens counted, result dropped",
                    run_id,
                    session_id,
                    status,
                    conversation.id,
                    tokens,
                )
                await emitter.conversation_updated(conversation)
                await uow.conversations.update(conversation)
                await uow.commit()
                await emitter.flush()
                return ApplyOutcome.IGNORED
            handoff_reason = None
            if status == "end":
                parsed = parse_end_node_result(end_node_result)
                if parsed.reply is None:
                    await store_message(
                        uow,
                        emitter,
                        conversation,
                        Role.SYSTEM,
                        "The flow finished without a reply.",
                        session_id=session_id,
                    )
                else:
                    await store_message(
                        uow,
                        emitter,
                        conversation,
                        Role.ASSISTANT,
                        parsed.reply,
                        actions=parsed.actions,
                        session_id=session_id,
                    )
                if parsed.request_human:
                    handoff_reason = "the flow asked for a human"
                if binding.broken_reason:
                    await uow.bindings.set_broken_reason(binding.id, None)
            else:
                await store_message(
                    uow,
                    emitter,
                    conversation,
                    Role.SYSTEM,
                    f"The flow stopped with status {status}.",
                    session_id=session_id,
                )
                handoff_reason = f"run {status}"
            conversation.count_turn(today)
            if holds_slot:
                self._release(conversation)
                await emitter.conversation(conversation, "run.finished", {"status": status})
            if handoff_reason:
                await hand_off(emitter, conversation, binding, handoff_reason)
            await emitter.conversation_updated(conversation)
            await uow.conversations.update(conversation)
            await uow.commit()
            await emitter.flush()
        return ApplyOutcome.APPLIED
