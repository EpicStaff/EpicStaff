from collections.abc import Callable
from datetime import datetime, timedelta

from domain.enums import TERMINAL_RUN_STATUSES
from domain.errors import RunNotFoundError
from domain.models import Conversation
from loguru import logger

from application.orchestrators.conversation import ConversationOrchestrator
from application.orchestrators.lifecycle import LifecycleTimers
from application.ports import AbstractFlowRunner, AbstractUnitOfWork

# Django stops retrying a callback after 24 h, so a receipt older than this guards nothing.
RECEIPT_RETENTION = timedelta(days=2)
# Conversations each inactivity rule handles per pass; the next pass takes the rest.
TIMER_BATCH = 500


class Reconciler:
    """Safety net behind the callback, and the clock of the desks' inactivity rules.

    Releases unconfirmed starts, finishes stuck runs, stops runaway ones, prunes old rows, then
    hands back visitors waiting past a desk's response time and closes idle Support
    conversations.
    """

    def __init__(
        self,
        uow_factory: Callable[[], AbstractUnitOfWork],
        *,
        conversations: ConversationOrchestrator,
        flows: AbstractFlowRunner,
        timers: LifecycleTimers,
        stale_after_seconds: int,
        unconfirmed_start_release_seconds: int,
        run_timeout_seconds: int,
        retention_seconds: int,
        visitor_token_idle_seconds: int,
        timer_batch: int = TIMER_BATCH,
    ):
        self._uow = uow_factory
        self._conversations = conversations
        self._flows = flows
        self._timers = timers
        self._timer_batch = timer_batch
        self._stale_after = timedelta(seconds=stale_after_seconds)
        self._unconfirmed_release = timedelta(seconds=unconfirmed_start_release_seconds)
        self._run_timeout = timedelta(seconds=run_timeout_seconds)
        self._retention = timedelta(seconds=retention_seconds)
        self._token_idle = timedelta(seconds=visitor_token_idle_seconds)

    async def run_once(self, now: datetime) -> int:
        """One pass. Returns how many unconfirmed starts and stuck runs were resolved; the
        inactivity rules' work is logged, not counted."""
        # Read and prune in one short transaction; no transaction stays open across Django calls.
        async with self._uow() as uow:
            unconfirmed = await uow.conversations.unconfirmed_starts(
                older_than=now - self._unconfirmed_release
            )
            stale = await uow.conversations.stale_runs(older_than=now - self._stale_after)
            pruned = await uow.events.delete_older_than(now - self._retention)
            await uow.receipts.delete_older_than(now - RECEIPT_RETENTION)
            idle_tokens = await uow.visitor_tokens.delete_idle(now - self._token_idle)
            await uow.commit()
        if pruned:
            logger.info("Pruned {} conversation events older than {}", pruned, self._retention)
        if idle_tokens:
            logger.info(
                "Pruned {} visitor tokens idle longer than {}", idle_tokens, self._token_idle
            )
        resolved = 0
        for conversation in unconfirmed:
            # Django never confirmed the run (start timed out, or the service stopped mid-start).
            # A late callback, if the run exists after all, still finds the receipt.
            logger.warning(
                "Conversation {} run {} unconfirmed after {}; releasing",
                conversation.id,
                conversation.active_run_id,
                self._unconfirmed_release,
            )
            try:
                resolved += await self._conversations.release_unconfirmed_start(
                    conversation.id, conversation.active_run_id
                )
            except Exception as error:  # one bad conversation must not stop the loop
                logger.error("Release of conversation {} failed: {}", conversation.id, error)
        for conversation, session_id in stale:
            try:
                resolved += await self._resolve(conversation, session_id, now)
            except Exception as error:  # one bad session must not stop the loop
                logger.error(
                    "Reconcile of conversation {} (session {}) failed: {}",
                    conversation.id,
                    session_id,
                    error,
                )
        await self._apply_inactivity_rules(now)
        return resolved

    async def _apply_inactivity_rules(self, now: datetime) -> None:
        # Hand-backs first, and close candidates read only afterwards: a hand-back posting a
        # notice is activity, so that conversation is not also closed as idle in this pass. One
        # handed back without a notice is no more active than before, and may be.
        async with self._uow() as uow:
            unanswered = await uow.conversations.unanswered_past_response_time(
                now, self._timer_batch
            )
        handed_back = 0
        for conversation_id in unanswered:
            try:
                handed_back += await self._timers.hand_back(conversation_id, now)
            except Exception as error:  # one bad conversation must not stop the loop
                logger.error("Hand-back of conversation {} failed: {}", conversation_id, error)
        async with self._uow() as uow:
            idle = await uow.conversations.inactive_past_close_after(now, self._timer_batch)
        closed = 0
        for conversation_id in idle:
            try:
                closed += await self._timers.close_inactive(conversation_id, now)
            except Exception as error:  # one bad conversation must not stop the loop
                logger.error("Idle close of conversation {} failed: {}", conversation_id, error)
        if handed_back or closed:
            logger.info(
                "Handed {} unanswered conversations back to the bot; closed {} idle ones",
                handed_back,
                closed,
            )

    async def _resolve(self, conversation: Conversation, session_id: int, now: datetime) -> int:
        run_id, org_id = conversation.active_run_id, conversation.org_id
        try:
            run = await self._flows.run_status(org_id, session_id)
        except RunNotFoundError:
            logger.warning("Session {} is gone from Django; releasing its conversation", session_id)
            await self._conversations.apply_run_result(
                run_id, session_id, "error", None, {}, final_usage=False
            )
            return 1
        if run.status in TERMINAL_RUN_STATUSES:
            result = (
                await self._flows.run_result(org_id, session_id) if run.status == "end" else None
            )
            await self._conversations.apply_run_result(
                run_id, session_id, run.status, result, run.token_usage, final_usage=False
            )
            return 1
        if conversation.active_since < now - self._run_timeout:
            logger.warning("Session {} exceeded the run timeout; stopping it", session_id)
            await self._flows.stop_run(session_id)
            # Usage read before the stop; Django's callback adds what the run used after it.
            await self._conversations.apply_run_result(
                run_id, session_id, "stop", None, run.token_usage, final_usage=False
            )
            return 1
        return 0
