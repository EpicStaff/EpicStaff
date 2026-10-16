from __future__ import annotations  # the `list` method shadows the builtin in annotations

import secrets
import unicodedata
from collections.abc import Callable
from uuid import UUID

from common.utils import new_id, utcnow
from domain.enums import BindingStyle, IdentityMode, OnBudgetExhausted, OnResponseTimeout
from domain.errors import (
    AliasReservedError,
    BotNameTakenError,
    ContractFailedError,
    FlowNotFoundError,
    NotFoundError,
    UnknownFlowError,
)
from domain.models import Binding
from domain.public_name import (
    PUBLIC_NAME_MAX_LENGTH,
    normalize_public_name,
    public_name_key,
    same_public_name,
)
from litestar.exceptions import ClientException

from application.orchestrators.budgets import BindingLimits
from application.ports import (
    AbstractFlowRunner,
    AbstractUnitOfWork,
    CallerCredentials,
    GraphContract,
)

DEFAULT_OPERATOR_DISPLAY_NAME = "Support"
# The request carries these as plain strings; the binding holds the enum members.
_ENUM_FIELDS = {
    "identity_mode": IdentityMode,
    "on_budget_exhausted": OnBudgetExhausted,
    "style": BindingStyle,
    "on_response_timeout": OnResponseTimeout,
}

SNIPPET = '<script src="{base}/chat/widget.js" data-public-key="{public_key}" data-chat-url="{base}/chat/" async></script>'


def contract_errors(contract: GraphContract) -> list[str]:
    """What stops this flow from serving chat; empty means it can."""
    errors = []
    if contract.start_variables is None:
        errors.append("The flow has no start node.")
    else:
        for name in ("chat_history", "user_message"):
            if name not in contract.start_variables:
                errors.append(f"Start node variables must declare `{name}`.")
    if contract.output_map is None:
        errors.append("The flow has no end node.")
    elif "reply" not in contract.output_map:
        errors.append("End node output map must contain `reply`.")
    return errors


def bot_name_from(desk_name: str) -> str | None:
    """The bot's name when none is given: the desk name, cut to a public name's length.

    Raises:
        ClientException: The desk name has a character a name shown to visitors cannot have.
    """
    try:
        return normalize_public_name(
            unicodedata.normalize("NFC", desk_name)[:PUBLIC_NAME_MAX_LENGTH]
        )
    except ValueError as error:
        raise ClientException(
            f"The desk name becomes the bot's name, which visitors see: {error} "
            "Set bot_display_name."
        ) from error


def new_public_key() -> str:
    return secrets.token_urlsafe(24)


def new_identity_secret() -> str:
    return secrets.token_urlsafe(32)


class BindingOrchestrator:
    def __init__(
        self,
        uow_factory: Callable[[], AbstractUnitOfWork],
        *,
        flows: AbstractFlowRunner,
        public_base_url: str,
        limits: BindingLimits,
    ):
        self._uow = uow_factory
        self._flows = flows
        self._limits = limits
        self._base_url = public_base_url.rstrip("/")

    def limits(self) -> BindingLimits:
        """The deployment's budget and duration defaults and caps; the same for every organization."""
        return self._limits

    async def list(self, org_id: int) -> list[Binding]:
        async with self._uow() as uow:
            return await uow.bindings.list(org_id)

    async def get(self, binding_id: UUID, org_id: int) -> Binding:
        async with self._uow() as uow:
            binding = await uow.bindings.get(binding_id, org_id=org_id)
        if binding is None:
            raise NotFoundError()
        return binding

    async def _check(self, caller: CallerCredentials, graph_id: int) -> list[str]:
        try:
            contract = await self._flows.graph_contract(caller, graph_id)
        except FlowNotFoundError as error:
            raise UnknownFlowError() from error
        return contract_errors(contract)

    async def _check_stored(
        self, caller: CallerCredentials, graph_id: int
    ) -> tuple[list[str], str | None]:
        """(errors, broken_reason) for a graph the binding already points at: a deleted flow is
        recorded on the binding instead of refusing the call."""
        try:
            return await self._check(caller, graph_id), None
        except UnknownFlowError as error:
            return [], error.message

    async def check_contract(self, caller: CallerCredentials, graph_id: int) -> list[str]:
        """What stops `graph_id` from serving chat, read as `caller`; empty means it can.

        Raises:
            UnknownFlowError: The graph is not in the caller's org (or does not exist).
            FlowForbiddenError: The caller lacks flows:read.
        """
        return await self._check(caller, graph_id)

    async def create(self, caller: CallerCredentials, values: dict) -> Binding:
        """`values` are the request fields; the graph is read as `caller`, in the caller's org.

        An omitted (None) budget, inactivity duration, style, response action or hand-back
        notice takes its default from `BindingLimits`. The binding is created active when the
        flow passes the contract, and paused with its errors stored when it does not.

        Raises:
            BudgetAboveCapError: A budget is above the configured cap.
            DurationAboveCapError: An inactivity duration is above the configured cap.
            UnknownFlowError: The graph is not in this org (or does not exist).
            FlowForbiddenError: The caller lacks flows:read.
        """
        values = self._limits.with_defaults(values)
        self._limits.check(values)
        org_id = caller.org_id
        errors = await self._check(caller, values["graph_id"])
        now = utcnow()
        signed = values["identity_mode"] == IdentityMode.SIGNED
        binding = Binding(
            id=new_id(),
            org_id=org_id,
            graph_id=values["graph_id"],
            name=values["name"],
            bot_display_name=values.get("bot_display_name") or bot_name_from(values["name"]),
            operator_display_name=values.get("operator_display_name")
            or DEFAULT_OPERATOR_DISPLAY_NAME,
            public_key=new_public_key(),
            allowed_origins=values["allowed_origins"],
            identity_mode=IdentityMode(values["identity_mode"]),
            identity_secret=new_identity_secret() if signed else None,
            is_active=True,
            history_window=values["history_window"],
            max_message_length=values["max_message_length"],
            max_turns=values["max_turns"],
            token_budget_per_conversation=values["token_budget_per_conversation"],
            daily_token_budget=values["daily_token_budget"],
            messages_per_minute=values["messages_per_minute"],
            on_budget_exhausted=OnBudgetExhausted(values["on_budget_exhausted"]),
            budget_exhausted_message=values["budget_exhausted_message"],
            handoff_enabled=values["handoff_enabled"],
            broken_reason=None,
            contract_errors=[],
            created_at=now,
            updated_at=now,
            style=BindingStyle(values["style"]),
            response_time_seconds=values["response_time_seconds"],
            on_response_timeout=OnResponseTimeout(values["on_response_timeout"]),
            handback_message=values["handback_message"],
            close_after_seconds=values["close_after_seconds"],
        )
        binding.record_contract(errors, None)
        async with self._uow() as uow:
            await uow.bindings.add(binding)
            await uow.commit()
        return binding

    async def update(
        self, binding_id: UUID, caller: CallerCredentials, changes: dict
    ) -> tuple[Binding, bool]:
        """Apply the given fields. Returns (binding, secret_rotated): the secret is shown only when it was just made.

        Every save re-checks the binding's flow (the new one when `graph_id` changes), read as
        `caller`. A failing contract is saved and pauses the binding; a passing one clears the
        stored errors but never resumes. A stored flow that was deleted is marked broken and
        paused. Changing `identity_mode` revokes every visitor token of the binding.

        Raises:
            BudgetAboveCapError: A budget is above the configured cap.
            DurationAboveCapError: An inactivity duration is above the configured cap.
            UnknownFlowError: `graph_id` changes to a graph not in this org; nothing is stored.
            FlowForbiddenError: The caller lacks flows:read; nothing is stored.
            BotNameTakenError: `bot_display_name` is an operator's alias on this desk, in any
                case; nothing is stored.
        """
        org_id = caller.org_id
        nulled = sorted(name for name, value in changes.items() if value is None)
        if nulled:
            raise ClientException(f"These fields cannot be null: {', '.join(nulled)}.")
        self._limits.check(changes)
        current = await self.get(binding_id, org_id)
        checked_graph_id = changes.get("graph_id", current.graph_id)
        # Checked before the row lock: no Django call inside the transaction.
        if checked_graph_id != current.graph_id:
            errors, broken_reason = await self._check(caller, checked_graph_id), None
        else:
            errors, broken_reason = await self._check_stored(caller, checked_graph_id)
        async with self._uow() as uow:
            binding = await uow.bindings.get(binding_id, org_id=org_id, for_update=True)
            if binding is None:
                raise NotFoundError()
            # Read under the row lock, which an alias claim's shared lock excludes: a claim that
            # committed first is seen here, and one still to come waits and then sees the new name.
            if "bot_display_name" in changes and await uow.operator_aliases.is_taken(
                binding.id, public_name_key(changes["bot_display_name"])
            ):
                raise BotNameTakenError()
            secret_rotated = False
            if "identity_mode" in changes and changes["identity_mode"] != binding.identity_mode:
                # Tokens were issued under the old identity rules; every visitor starts over.
                await uow.visitor_tokens.delete_for_binding(binding.id)
                if changes["identity_mode"] == IdentityMode.SIGNED:
                    binding.identity_secret = new_identity_secret()
                    secret_rotated = True
            for name, value in changes.items():
                setattr(binding, name, _ENUM_FIELDS[name](value) if name in _ENUM_FIELDS else value)
            # shortcut: a concurrent save moved the row to another graph between the check and the
            # lock, so the check describes neither graph and the stored contract fields are kept; the
            # CHECK constraint still refuses an active row with errors. Re-check under the lock if this
            # ever matters.
            if binding.graph_id == checked_graph_id:
                binding.record_contract(errors, broken_reason)
            binding.updated_at = utcnow()
            await uow.bindings.update(binding)
            await uow.commit()
        return binding, secret_rotated

    async def pause(self, binding_id: UUID, org_id: int) -> Binding:
        """Stop the widget answering; test conversations keep working. Pausing a paused binding is a no-op."""
        async with self._uow() as uow:
            binding = await uow.bindings.get(binding_id, org_id=org_id, for_update=True)
            if binding is None:
                raise NotFoundError()
            binding.is_active = False
            binding.updated_at = utcnow()
            await uow.bindings.update(binding)
            await uow.commit()
        return binding

    async def resume(self, binding_id: UUID, caller: CallerCredentials) -> Binding:
        """Re-check the flow as `caller` and activate when it passes.

        A failing check is stored on the binding (and committed) before the error is raised, so
        the operator sees the fresh errors; the binding stays paused.

        Raises:
            ContractFailedError: The flow cannot serve chat.
            UnknownFlowError: The flow was deleted; `broken_reason` is stored.
            FlowForbiddenError: The caller lacks flows:read; nothing is stored.
        """
        current = await self.get(binding_id, caller.org_id)
        errors, broken_reason = await self._check_stored(caller, current.graph_id)
        failure = None
        async with self._uow() as uow:
            binding = await uow.bindings.get(binding_id, org_id=caller.org_id, for_update=True)
            if binding is None:
                raise NotFoundError()
            # shortcut: as in update, a graph changed since the check keeps its stored contract fields.
            if binding.graph_id == current.graph_id:
                binding.record_contract(errors, broken_reason)
            if binding.broken_reason:
                failure = UnknownFlowError()
            elif binding.contract_errors:
                failure = ContractFailedError(binding.contract_errors)
            else:
                binding.resume()
            binding.updated_at = utcnow()
            await uow.bindings.update(binding)
            await uow.commit()
        if failure:
            raise failure
        return binding

    async def delete(self, binding_id: UUID, org_id: int) -> None:
        async with self._uow() as uow:
            deleted = await uow.bindings.delete(binding_id, org_id)
            await uow.commit()
        if not deleted:
            raise NotFoundError()

    async def rotate_key(self, binding_id: UUID, org_id: int) -> Binding:
        """New public key; every visitor token of the binding is revoked with the old key.

        Streams already open, and stream tickets issued in the last CHAT_TICKET_TTL, keep working
        until CHAT_STREAM_MAX_LIFETIME; a reconnect is then refused.
        """
        async with self._uow() as uow:
            binding = await uow.bindings.get(binding_id, org_id=org_id, for_update=True)
            if binding is None:
                raise NotFoundError()
            binding.public_key = new_public_key()
            # A rotation is how an operator cuts off a leaked key, so its visitor tokens go too.
            await uow.visitor_tokens.delete_for_binding(binding.id)
            binding.updated_at = utcnow()
            await uow.bindings.update(binding)
            await uow.commit()
        return binding

    async def my_aliases(self, org_id: int, user_id: int) -> list[tuple[UUID, str]]:
        """The caller's names on the org's desks, as `(desk id, alias)`."""
        async with self._uow() as uow:
            return await uow.operator_aliases.mine(org_id, user_id)

    async def set_my_alias(
        self, binding_id: UUID, org_id: int, user_id: int, alias: str | None
    ) -> tuple[str | None, str]:
        """Set or clear the caller's name on a desk, which visitors see on their later replies.

        Messages already sent keep the name they were sent with.

        Args:
            alias: Normalized by `normalize_public_name`; None clears it, and visitors see the
                desk's operator name again.

        Returns:
            The alias, and the name visitors now see on the caller's replies there.

        Raises:
            NotFoundError: No such desk in `org_id`.
            AliasReservedError: The desk's bot name, in any case: visitors could not tell the
                operator from the bot.
            AliasTakenError: Another operator's alias on the desk, in any case.
        """
        async with self._uow() as uow:
            # Shared lock, as a create takes, held to commit: a bot rename (FOR UPDATE) waits and
            # then sees this alias, and a rename that locked first makes this read wait and return
            # the new bot name. A desk delete waits rather than deadlocks.
            binding = await uow.bindings.get(binding_id, org_id=org_id, for_share=True)
            if binding is None:
                raise NotFoundError()
            if alias is None:
                await uow.operator_aliases.clear(binding.id, user_id)
            elif same_public_name(alias, binding.bot_display_name):
                raise AliasReservedError()
            else:
                await uow.operator_aliases.set(binding.id, user_id, alias, utcnow())
            await uow.commit()
        return alias, binding.operator_visible_name(alias)

    async def snippet(self, binding_id: UUID, org_id: int) -> dict:
        binding = await self.get(binding_id, org_id)
        return {
            "public_key": binding.public_key,
            "chat_base_url": f"{self._base_url}/chat/",
            "snippet": SNIPPET.format(base=self._base_url, public_key=binding.public_key),
        }
