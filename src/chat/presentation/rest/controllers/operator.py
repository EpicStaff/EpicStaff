from uuid import UUID

from application.orchestrators.bindings import BindingOrchestrator
from application.orchestrators.conversation import ConversationOrchestrator
from application.orchestrators.identity import Operator
from application.orchestrators.operators import OperatorOrchestrator
from application.orchestrators.streams import StreamOrchestrator
from application.ports import AbstractTickets, CallerCredentials
from domain.enums import InboxOrder, InboxSection, Mode
from domain.errors import ForbiddenError, InvalidTokenError
from domain.search import InboxSearch
from litestar import Controller, Request, delete, get, patch, post, put, status_codes
from litestar.exceptions import ValidationException
from litestar.params import Parameter
from litestar.response import ServerSentEvent

from presentation.rest.guards import chats_guard
from presentation.rest.request_context import bearer_token, last_event_id
from presentation.rest.schemas import operator as schemas
from presentation.rest.schemas.public import TicketOutput

PAGE_SIZE = 50
# Who builds desks, as opposed to an operator (read + use) who only answers visitors: tests and the embed snippet
# are theirs.
DESK_BUILDER_ACTIONS = ("create", "update")
MAX_PAGE = 100


def _caller(request: Request, operator: Operator) -> CallerCredentials:
    # chats_guard already resolved this token, so it is present.
    return CallerCredentials(org_id=operator.org_id, bearer_token=bearer_token(request) or "")


class OperatorController(Controller):
    """EpicStaff users with the JWT + org header; every route names the `chats` action it needs."""

    path = "/chat/operator/v1"
    tags = ("Operator",)
    guards = [chats_guard]

    # ---- bindings ----

    @get(path="/bindings", opt={"chats_action": "read"})
    async def list_bindings(
        self, operator: Operator, bindings: BindingOrchestrator
    ) -> list[schemas.BindingOutput]:
        return [
            schemas.BindingOutput.model_validate(b) for b in await bindings.list(operator.org_id)
        ]

    @get(path="/bindings/my-aliases", opt={"chats_action": "read"})
    async def my_aliases(
        self, operator: Operator, bindings: BindingOrchestrator
    ) -> list[schemas.OperatorAliasOutput]:
        return [
            schemas.OperatorAliasOutput(binding_id=binding_id, alias=alias)
            for binding_id, alias in await bindings.my_aliases(operator.org_id, operator.user_id)
        ]

    @put(
        path="/bindings/{binding_id:uuid}/my-alias",
        opt={"chats_action": "use"},
        summary="Set or clear your name on this desk",
    )
    async def set_my_alias(
        self,
        binding_id: UUID,
        data: schemas.MyAliasInput,
        operator: Operator,
        bindings: BindingOrchestrator,
    ) -> schemas.MyAliasOutput:
        alias, visible_name = await bindings.set_my_alias(
            binding_id, operator.org_id, operator.user_id, data.alias
        )
        return schemas.MyAliasOutput(binding_id=binding_id, alias=alias, visible_name=visible_name)

    @get(path="/bindings/limits", opt={"chats_action": "read"})
    async def binding_limits(self, bindings: BindingOrchestrator) -> schemas.BindingLimitsOutput:
        limits = bindings.limits()
        return schemas.BindingLimitsOutput(
            defaults=schemas.LimitDefaults(**limits.defaults),
            caps=schemas.LimitCaps(**limits.caps),
        )

    @get(path="/bindings/contract", opt={"chats_action": "read"})
    async def check_contract(
        self,
        request: Request,
        operator: Operator,
        bindings: BindingOrchestrator,
        graph_id: int = Parameter(ge=1),
    ) -> schemas.ContractCheckOutput:
        errors, missing = await bindings.check_contract(_caller(request, operator), graph_id)
        return schemas.ContractCheckOutput(contract_errors=errors, contract_missing=missing)

    @post(
        path="/bindings", status_code=status_codes.HTTP_201_CREATED, opt={"chats_action": "create"}
    )
    async def create_binding(
        self,
        request: Request,
        data: schemas.BindingInput,
        operator: Operator,
        bindings: BindingOrchestrator,
    ) -> schemas.BindingWithSecretOutput:
        binding = await bindings.create(_caller(request, operator), data.model_dump())
        return schemas.BindingWithSecretOutput.model_validate(binding)

    @get(path="/bindings/{binding_id:uuid}", opt={"chats_action": "read"})
    async def get_binding(
        self, binding_id: UUID, operator: Operator, bindings: BindingOrchestrator
    ) -> schemas.BindingOutput:
        return schemas.BindingOutput.model_validate(await bindings.get(binding_id, operator.org_id))

    @patch(path="/bindings/{binding_id:uuid}", opt={"chats_action": "update"})
    async def update_binding(
        self,
        request: Request,
        binding_id: UUID,
        data: schemas.BindingPatch,
        operator: Operator,
        bindings: BindingOrchestrator,
    ) -> schemas.BindingWithSecretOutput | schemas.BindingOutput:
        binding, secret_rotated = await bindings.update(
            binding_id, _caller(request, operator), data.model_dump(exclude_unset=True)
        )
        schema = schemas.BindingWithSecretOutput if secret_rotated else schemas.BindingOutput
        return schema.model_validate(binding)

    @delete(
        path="/bindings/{binding_id:uuid}",
        status_code=status_codes.HTTP_204_NO_CONTENT,
        opt={"chats_action": "delete"},
    )
    async def delete_binding(
        self, binding_id: UUID, operator: Operator, bindings: BindingOrchestrator
    ) -> None:
        await bindings.delete(binding_id, operator.org_id)

    @post(
        path="/bindings/{binding_id:uuid}/rotate-key",
        status_code=status_codes.HTTP_200_OK,
        opt={"chats_action": "update"},
    )
    async def rotate_key(
        self, binding_id: UUID, operator: Operator, bindings: BindingOrchestrator
    ) -> schemas.BindingOutput:
        return schemas.BindingOutput.model_validate(
            await bindings.rotate_key(binding_id, operator.org_id)
        )

    @post(
        path="/bindings/{binding_id:uuid}/pause",
        status_code=status_codes.HTTP_200_OK,
        opt={"chats_action": "update"},
    )
    async def pause_binding(
        self, binding_id: UUID, operator: Operator, bindings: BindingOrchestrator
    ) -> schemas.BindingOutput:
        return schemas.BindingOutput.model_validate(
            await bindings.pause(binding_id, operator.org_id)
        )

    @post(
        path="/bindings/{binding_id:uuid}/resume",
        status_code=status_codes.HTTP_200_OK,
        opt={"chats_action": "update"},
    )
    async def resume_binding(
        self,
        request: Request,
        binding_id: UUID,
        operator: Operator,
        bindings: BindingOrchestrator,
    ) -> schemas.BindingOutput:
        return schemas.BindingOutput.model_validate(
            await bindings.resume(binding_id, _caller(request, operator))
        )

    @get(path="/bindings/{binding_id:uuid}/snippet", opt={"chats_action": DESK_BUILDER_ACTIONS})
    async def snippet(
        self, binding_id: UUID, operator: Operator, bindings: BindingOrchestrator
    ) -> schemas.SnippetOutput:
        return schemas.SnippetOutput(**await bindings.snippet(binding_id, operator.org_id))

    @post(
        path="/bindings/{binding_id:uuid}/test-conversation",
        status_code=status_codes.HTTP_201_CREATED,
        opt={"chats_action": DESK_BUILDER_ACTIONS},
    )
    async def test_conversation(
        self, binding_id: UUID, operator: Operator, conversations: ConversationOrchestrator
    ) -> schemas.TestConversationOutput:
        row, token = await conversations.create_test(binding_id, operator.org_id)
        return schemas.TestConversationOutput(
            visitor_token=token, conversation=schemas.ConversationOutput.model_validate(row)
        )

    @post(
        path="/conversations/{conversation_id:uuid}/visitor-token",
        status_code=status_codes.HTTP_201_CREATED,
        opt={"chats_action": DESK_BUILDER_ACTIONS},
        summary="A new visitor token for a test conversation",
    )
    async def test_visitor_token(
        self, conversation_id: UUID, operator: Operator, conversations: ConversationOrchestrator
    ) -> schemas.VisitorTokenOutput:
        token = await conversations.issue_test_visitor_token(conversation_id, operator.org_id)
        return schemas.VisitorTokenOutput(visitor_token=token)

    # ---- inbox stream ----

    @post(
        path="/inbox/stream-ticket",
        status_code=status_codes.HTTP_201_CREATED,
        opt={"chats_action": "read"},
    )
    async def inbox_ticket(self, operator: Operator, tickets: AbstractTickets) -> TicketOutput:
        ticket, expires_in = await tickets.issue(
            {"kind": "inbox", "org_id": operator.org_id, "user_id": operator.user_id}
        )
        return TicketOutput(ticket=ticket, expires_in=expires_in)

    # ---- conversations ----

    @get(path="/conversations", opt={"chats_action": "read"})
    async def list_conversations(
        self,
        operator: Operator,
        operators: OperatorOrchestrator,
        section: InboxSection,
        binding: UUID | None = None,
        mode: Mode | None = None,
        mine: bool = Parameter(
            default=False, description="Only conversations the caller holds; none in bot."
        ),
        order: InboxOrder = Parameter(
            default=InboxOrder.NEWEST,
            description="In progress, bot and test; waiting is always longest wait first, "
            "closed always most recently closed first.",
        ),
        q: str | None = Parameter(
            default=None,
            description="Visitor number (12, #12, visitor 12), a signed visitor's id prefix or "
            "the holder's name; case-insensitive.",
        ),
        cursor: str | None = None,
    ) -> schemas.ConversationPageOutput:
        if mode is not None and (section != InboxSection.HUMAN or mode == Mode.BOT):
            raise ValidationException("`mode` filters the human section: awaiting_human or human.")
        if section == InboxSection.HUMAN and (mine or q is not None):
            raise ValidationException(
                "`mine` and `q` apply to waiting, in_progress, bot, test and closed."
            )
        if section == InboxSection.TEST and not operator.allows_any(DESK_BUILDER_ACTIONS):
            raise ForbiddenError("chats:create or chats:update is required.")
        rows, next_key = await operators.list_conversations(
            operator.org_id,
            binding,
            section,
            schemas.decode_inbox_cursor(cursor) if cursor is not None else None,
            PAGE_SIZE,
            mode=mode,
            order=order,
            holder_id=operator.user_id if mine else None,
            search=InboxSearch.parse(q) if q is not None else None,
        )
        return schemas.ConversationPageOutput(
            results=[schemas.ConversationOutput.model_validate(row) for row in rows],
            next_cursor=schemas.encode_inbox_cursor(next_key) if next_key else None,
        )

    @get(path="/inbox/badges", opt={"chats_action": "read"})
    async def inbox_badges(
        self, operator: Operator, operators: OperatorOrchestrator
    ) -> schemas.InboxBadgesOutput:
        badges = await operators.badges(operator.org_id)
        return schemas.InboxBadgesOutput(
            waiting=[schemas.InboxBadgeOutput.model_validate(badge) for badge in badges]
        )

    @get(path="/conversations/{conversation_id:uuid}", opt={"chats_action": "read"})
    async def conversation(
        self, conversation_id: UUID, operator: Operator, operators: OperatorOrchestrator
    ) -> schemas.ConversationOutput:
        return schemas.ConversationOutput.model_validate(
            await operators.get(conversation_id, operator.org_id)
        )

    @get(path="/conversations/{conversation_id:uuid}/messages", opt={"chats_action": "read"})
    async def messages(
        self,
        conversation_id: UUID,
        operator: Operator,
        operators: OperatorOrchestrator,
        before: UUID | None = None,
        limit: int = Parameter(default=50, ge=1, le=MAX_PAGE),
    ) -> list[schemas.OperatorMessageOutput]:
        page, names = await operators.messages(conversation_id, operator.org_id, before, limit)
        return [
            schemas.OperatorMessageOutput.from_message(message, names.get(message.author_user_id))
            for message in page
        ]

    @post(
        path="/conversations/{conversation_id:uuid}/claim",
        status_code=status_codes.HTTP_200_OK,
        opt={"chats_action": "use"},
    )
    async def claim(
        self,
        conversation_id: UUID,
        operator: Operator,
        operators: OperatorOrchestrator,
        data: schemas.ClaimInput | None = None,
    ) -> schemas.ConversationOutput:
        row = await operators.claim(
            conversation_id,
            operator.org_id,
            operator.user_id,
            force=bool(data and data.force),
            display_name=operator.display_name,
        )
        return schemas.ConversationOutput.model_validate(row)

    @post(
        path="/conversations/{conversation_id:uuid}/close",
        status_code=status_codes.HTTP_200_OK,
        opt={"chats_action": "use"},
        summary="Close the conversation for good: Resolve, or Close conversation",
    )
    async def close(
        self,
        conversation_id: UUID,
        operator: Operator,
        operators: OperatorOrchestrator,
        data: schemas.CloseInput | None = None,
    ) -> schemas.ConversationOutput:
        row = await operators.close(
            conversation_id,
            operator.org_id,
            operator.user_id,
            force=bool(data and data.force),
            display_name=operator.display_name,
        )
        return schemas.ConversationOutput.model_validate(row)

    @post(
        path="/conversations/{conversation_id:uuid}/release",
        status_code=status_codes.HTTP_200_OK,
        opt={"chats_action": "use"},
    )
    async def release(
        self, conversation_id: UUID, operator: Operator, operators: OperatorOrchestrator
    ) -> schemas.ConversationOutput:
        return schemas.ConversationOutput.model_validate(
            await operators.release(conversation_id, operator.org_id, operator.user_id)
        )

    @post(
        path="/conversations/{conversation_id:uuid}/messages",
        status_code=status_codes.HTTP_201_CREATED,
        opt={"chats_action": "use"},
    )
    async def reply(
        self,
        conversation_id: UUID,
        data: schemas.ReplyInput,
        operator: Operator,
        operators: OperatorOrchestrator,
    ) -> schemas.OperatorMessageOutput:
        message, author_name = await operators.reply(
            conversation_id,
            operator.org_id,
            operator.user_id,
            data.content,
            display_name=operator.display_name,
        )
        return schemas.OperatorMessageOutput.from_message(message, author_name)


class InboxStreamController(Controller):
    """Same path, no guard: EventSource cannot send headers, so the ticket minted under the guard is the credential.

    Litestar merges guards across layers, so the stream cannot opt out on `OperatorController`.
    """

    path = "/chat/operator/v1"
    tags = ("Operator",)

    @get(
        path="/inbox/stream",
        summary="SSE: message.created, conversation.updated, conversation.closed",
    )
    async def inbox_stream(
        self,
        request: Request,
        tickets: AbstractTickets,
        streams: StreamOrchestrator,
        ticket: str | None = None,
    ) -> ServerSentEvent:
        payload = await tickets.consume(ticket) if ticket else None
        if not payload or payload.get("kind") != "inbox":
            raise InvalidTokenError("Invalid or expired stream ticket.")
        return ServerSentEvent(
            await streams.inbox_stream(
                int(payload["org_id"]), int(payload["user_id"]), last_event_id(request)
            )
        )
