import json
import time
from uuid import UUID

from application.orchestrators.conversation import ConversationOrchestrator
from domain.enums import TERMINAL_RUN_STATUSES
from domain.errors import UnknownRunError
from infrastructure.callback_verifier import (
    SESSION_ID_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    verify,
)
from litestar import Controller, Request, post, status_codes
from litestar.exceptions import ClientException


class InternalController(Controller):
    """Reachable only inside the compose network (nginx answers 404 for /chat/internal/)."""

    path = "/chat/internal/v1"
    tags = ("Internal",)

    @post(
        path="/session-callbacks/{run_id:uuid}",
        status_code=status_codes.HTTP_200_OK,
        summary="Signed completion callback from Django",
    )
    async def session_callback(
        self, request: Request, run_id: UUID, conversations: ConversationOrchestrator
    ) -> dict[str, str]:
        """Apply a run's result. The run id comes from the URL the chat handed Django at start.

        The session id is bound to the run on first sight, so the callback works even when
        Django's start response never reached the chat. Unknown run → 404, so Django retries.
        """
        raw_session_id = request.headers.get(SESSION_ID_HEADER)
        if not raw_session_id or not (raw_session_id.isascii() and raw_session_id.isdigit()):
            raise ClientException(f"{SESSION_ID_HEADER} header is required.")
        session_id = int(raw_session_id)
        body = await request.body()
        receipt = await conversations.receipt(run_id)
        if receipt is None:
            raise UnknownRunError()
        if not receipt.secret:
            # Already applied, or refused at start: no secret left to verify against. 200 stops retries.
            return {"result": "ignored"}
        verify(
            receipt.secret,
            request.headers.get(TIMESTAMP_HEADER),
            body,
            request.headers.get(SIGNATURE_HEADER),
            now=int(time.time()),
            max_skew_seconds=request.app.state.settings.CHAT_CALLBACK_MAX_SKEW,
        )
        try:
            payload = json.loads(body)
        except ValueError as error:
            raise ClientException("Body is not JSON.") from error
        if (
            not isinstance(payload, dict)
            or payload.get("session_id") != session_id
            or not isinstance(payload.get("status"), str)
        ):
            raise ClientException("Body does not describe the session named in the header.")
        if payload["status"] not in TERMINAL_RUN_STATUSES:
            raise ClientException(f"status must be one of {sorted(TERMINAL_RUN_STATUSES)}.")
        outcome = await conversations.apply_run_result(
            run_id,
            session_id,
            payload["status"],
            payload.get("end_node_result"),
            payload.get("token_usage") or {},
        )
        return {"result": outcome.value}
