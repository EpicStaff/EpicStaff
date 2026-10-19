from uuid import UUID

from application.orchestrators.conversation import ConversationOrchestrator
from application.orchestrators.streams import StreamOrchestrator
from application.ports import AbstractTickets
from domain.errors import InvalidTokenError
from litestar import Controller, Request, get, post, status_codes
from litestar.params import Parameter
from litestar.response import ServerSentEvent

from presentation.rest.request_context import bearer_token, client_ip, last_event_id, origin
from presentation.rest.schemas import public as public_schemas

MAX_PAGE = 100
# The largest legitimate body is a 100,000-character message fully \u-escaped (600 KB) plus the
# action and chat_extra_data caps; anything bigger is refused before it is decoded.
PUBLIC_MAX_BODY_BYTES = 1024 * 1024


class PublicController(Controller):
    """The widget contract. Auth is the visitor token; the Origin header is checked by the orchestrator."""

    path = "/chat/public/v1"
    tags = ("Public",)
    request_max_body_size = PUBLIC_MAX_BODY_BYTES

    @post(
        path="/conversations",
        status_code=status_codes.HTTP_201_CREATED,
        summary="Open or resume a conversation",
    )
    async def create_conversation(
        self,
        data: public_schemas.CreateConversationInput,
        request: Request,
        conversations: ConversationOrchestrator,
    ) -> public_schemas.CreateConversationOutput:
        conversation, token, binding = await conversations.create(
            data.public_key,
            data.identity_token,
            origin(request),
            client_ip(request),
            chat_extra_data=data.chat_extra_data,
        )
        return public_schemas.CreateConversationOutput(
            conversation_id=conversation.id,
            visitor_token=token,
            bot_display_name=binding.bot_display_name,
            operator_display_name=binding.operator_display_name,
        )

    @get(path="/conversations/{conversation_id:uuid}", summary="Mode, run state and status")
    async def state(
        self, conversation_id: UUID, request: Request, conversations: ConversationOrchestrator
    ) -> public_schemas.ConversationStateOutput:
        conversation, binding = await conversations.resolve(conversation_id, bearer_token(request))
        return public_schemas.ConversationStateOutput.from_conversation(conversation, binding)

    @post(
        path="/conversations/{conversation_id:uuid}/end",
        status_code=status_codes.HTTP_200_OK,
        summary="Close the conversation: the visitor's Start a new chat",
    )
    async def end(
        self, conversation_id: UUID, request: Request, conversations: ConversationOrchestrator
    ) -> public_schemas.ConversationStateOutput:
        conversation, binding = await conversations.end(
            conversation_id, bearer_token(request), origin(request)
        )
        return public_schemas.ConversationStateOutput.from_conversation(conversation, binding)

    @get(path="/conversations/{conversation_id:uuid}/messages", summary="Newest page, oldest first")
    async def messages(
        self,
        conversation_id: UUID,
        request: Request,
        conversations: ConversationOrchestrator,
        before: UUID | None = None,
        limit: int = Parameter(default=50, ge=1, le=MAX_PAGE),
    ) -> list[public_schemas.PublicMessageOutput]:
        await conversations.resolve(conversation_id, bearer_token(request))
        page = await conversations.messages(conversation_id, before, limit)
        return [public_schemas.PublicMessageOutput.model_validate(message) for message in page]

    @post(
        path="/conversations/{conversation_id:uuid}/messages",
        status_code=status_codes.HTTP_202_ACCEPTED,
        summary="Send a message",
    )
    async def send(
        self,
        conversation_id: UUID,
        data: public_schemas.SendMessageInput,
        request: Request,
        conversations: ConversationOrchestrator,
    ) -> public_schemas.SendMessageOutput:
        result = await conversations.submit(
            conversation_id,
            bearer_token(request),
            data.content,
            origin(request),
            client_ip(request),
            action=data.action,
            chat_extra_data=data.chat_extra_data,
        )
        return public_schemas.SendMessageOutput(
            message_id=result.message_id, state=result.state.value
        )

    @post(
        path="/conversations/{conversation_id:uuid}/stream-ticket",
        status_code=status_codes.HTTP_201_CREATED,
        summary="Single-use ticket for the stream",
    )
    async def stream_ticket(
        self,
        conversation_id: UUID,
        request: Request,
        conversations: ConversationOrchestrator,
        tickets: AbstractTickets,
    ) -> public_schemas.TicketOutput:
        conversation, _ = await conversations.resolve(conversation_id, bearer_token(request))
        ticket, expires_in = await tickets.issue(
            {"kind": "conversation", "conversation_id": str(conversation.id)}
        )
        return public_schemas.TicketOutput(ticket=ticket, expires_in=expires_in)

    @get(
        path="/conversations/{conversation_id:uuid}/stream",
        summary="SSE: message.created, run.started, run.finished, mode.changed, conversation.closed",
    )
    async def stream(
        self,
        conversation_id: UUID,
        request: Request,
        tickets: AbstractTickets,
        streams: StreamOrchestrator,
        conversations: ConversationOrchestrator,
        ticket: str | None = None,
    ) -> ServerSentEvent:
        payload = await tickets.consume(ticket) if ticket else None
        if (
            not payload
            or payload.get("kind") != "conversation"
            or payload.get("conversation_id") != str(conversation_id)
        ):
            raise InvalidTokenError("Invalid or expired stream ticket.")
        await conversations.check_streamable(conversation_id)
        return ServerSentEvent(
            await streams.conversation_stream(
                conversation_id, last_event_id(request), client_ip(request)
            )
        )
