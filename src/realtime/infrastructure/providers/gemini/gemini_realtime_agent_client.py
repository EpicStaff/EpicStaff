import asyncio
import audioop
import base64
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from application.tool_manager_service import ToolManagerService
from domain.models.realtime_tool import RealtimeTool
from google import genai
from google.genai import types
from loguru import logger
from utils.public_error import (
    PublicErrorMessage,
    build_public_error_message,
    new_error_correlation_id,
)
from websockets.exceptions import ConnectionClosed, InvalidStatus

from infrastructure.providers.base_realtime_agent_client import BaseRealtimeAgentClient
from infrastructure.providers.gemini.event_handlers.gemini_client_event_handler import (
    GeminiClientEventHandler,
)
from infrastructure.providers.gemini.event_handlers.gemini_server_event_handler import (
    GeminiServerEventHandler,
)

# Close codes a server sends when it, not the request, is the problem (going away,
# internal error, restart, try again later, bad gateway): the handle may still be
# good, so it is kept and the connect is retried.
_TRANSIENT_CLOSE_CODES = frozenset({1001, 1011, 1012, 1013, 1014})

# What opening a session raises: a close frame or drop during setup, a rejected
# websocket upgrade, or the network.
_CONNECT_ERRORS = (ConnectionClosed, InvalidStatus, OSError)

# Waits before the 2nd and 3rd attempt of a connect that failed transiently.
_CONNECT_RETRY_BACKOFF_SECONDS = (0.5, 1.5)

# Upper bound on one connect(), retries and fresh fallback included. Each attempt
# can take websockets' 10 s open timeout, and the SDK waits for the setup reply
# with no timeout at all, so without this a caller could sit in silence for
# minutes. Past it the connect fails and the handle is kept.
_CONNECT_DEADLINE_SECONDS = 15.0

# Upgrade rejections worth another try: request timeout, rate limit, server errors.
# Any other status (401, 403, 404, ...) means bad key, model or request; retrying
# or switching to a fresh session would be rejected the same way.
_RETRYABLE_UPGRADE_STATUSES = frozenset({408, 429})


def _is_permanent_upgrade_failure(error: Exception) -> bool:
    if not isinstance(error, InvalidStatus):
        return False
    status = error.response.status_code
    return status not in _RETRYABLE_UPGRADE_STATUSES and status < 500


# Reconnects in a row whose sessions closed without delivering a single message.
# Past this the server is closing every session it opens; reopening would only loop.
_MAX_RECONNECTS_WITHOUT_A_MESSAGE = 3


def _is_resumption_refusal(error: Exception) -> bool:
    """Return whether Gemini rejected the setup message, which carries the handle.

    The handle travels in the setup message sent after the websocket upgrade, so an
    upgrade failure (InvalidStatus: bad key or model, 429, 5xx) says nothing about it.
    A close frame answering the setup does, unless its code says the server itself
    is failing. A connection dropped without a close frame is transient.
    """
    if not isinstance(error, ConnectionClosed) or error.rcvd is None:
        return False
    # NOTE: an expired or unknown handle is assumed to be answered with 1007 (invalid
    # payload) or 1008 (policy violation); not yet checked against a real expired handle.
    # Any other non-transient code is deliberately treated as a refusal too: keeping a
    # handle the server keeps rejecting would fail every later reconnect.
    return error.rcvd.code not in _TRANSIENT_CLOSE_CODES


class GeminiRealtimeAgentClient(BaseRealtimeAgentClient):
    """
    Google Gemini Live API adapter.  Implements IRealtimeAgentClient via BaseRealtimeAgentClient.

    Audio paths:
    - Browser input: frontend sends 24kHz PCM via process_message() →
      GeminiClientEventHandler downsamples 24k→16k → send_realtime_input
    - Twilio input: VoiceCallService calls send_audio(ulaw8k_b64) →
      audioop converts µ-law 8kHz → PCM 16kHz → send_realtime_input
    - Browser output: Gemini outputs 24kHz PCM — passed through as-is
    - Twilio output: GeminiServerEventHandler converts PCM 24kHz → µ-law 8kHz
    """

    def __init__(
        self,
        api_key: str,
        connection_key: str,
        on_server_event: Callable[[dict], Awaitable[None]] | None = None,
        tool_manager_service: ToolManagerService = None,
        rt_tools: list[RealtimeTool] | None = None,
        model: str = "gemini-2.0-flash-live-001",
        voice: str = "Puck",
        instructions: str = "You are a helpful assistant",
        temperature: float | None = None,
        org_id: int | None = None,
        user_id: int | None = None,
    ):
        super().__init__(
            api_key=api_key,
            connection_key=connection_key,
            on_server_event=on_server_event,
            org_id=org_id,
            user_id=user_id,
        )

        valid_gemini_voices = {
            "Puck",
            "Charon",
            "Kore",
            "Fenrir",
            "Aoede",
            "Leda",
            "Orus",
            "Zephyr",
        }
        self.tool_manager_service = tool_manager_service
        self.model = model
        self.voice = voice if voice in valid_gemini_voices else "Puck"
        if self.voice != voice:
            logger.warning(f"Gemini: invalid voice '{voice}', falling back to 'Puck'")
        self.instructions = instructions
        self.temperature = temperature

        self._genai_client = genai.Client(api_key=api_key)
        self._session = None
        self._session_cm = None
        # Incremented on every connect — lets call_tool() detect session replacement
        self._session_version: int = 0
        # Prevents concurrent close() calls from racing on _session_cm.__aexit__
        self._close_lock = asyncio.Lock()

        # Stateful resampling state for Twilio paths
        self._resample_state_in = None  # µ-law 8kHz → PCM 16kHz
        self._resample_state_out = None  # PCM 24kHz → µ-law 8kHz

        # Rolling buffer: always keeps the last `rolling_buffer_secs` seconds of user audio.
        # On reconnect after session close, the buffer is replayed to the new session so
        # Gemini hears the user's speech that happened during the interruption window.
        # 16kHz 16-bit mono = 32 000 B/s → 5 s ≈ 160 KB, negligible overhead.
        rolling_buffer_secs = 5.0
        self._audio_rolling_buffer: deque[tuple[float, bytes]] = deque()
        self._rolling_buffer_secs: float = rolling_buffer_secs

        # Newest resumable session handle from Gemini's session_resumption_update.
        # A reconnect passes it so the server restores the conversation itself;
        # without one the new session starts from the instructions alone.
        self._resumption_handle: str | None = None
        # Monotonic time the handle above was stored: a session resumed from it
        # already holds the caller's audio up to then, so only newer audio is replayed.
        self._resumption_handle_time: float | None = None
        # Replay cut-off for the current session: None replays the whole rolling
        # buffer (a fresh session), a time replays only chunks newer than it.
        self._replay_audio_after: float | None = None
        # True while a session opened with a handle has not yet sent a
        # session_resumption_update, the only proof that Gemini accepted the handle.
        self._resumption_unconfirmed = False

        self.server_event_handler = GeminiServerEventHandler(self)
        self.client_event_handler = GeminiClientEventHandler(self)

        self.tools = self._build_tools(rt_tools or [])

    def _build_tools(self, rt_tools: list[RealtimeTool]) -> list:
        """Convert RealtimeTool list to Gemini function_declarations format."""
        if not rt_tools:
            return []
        declarations = []
        for t in rt_tools:
            if isinstance(t, dict):
                name = t["name"]
                description = t.get("description", name)
                parameters = t["parameters"]
            else:
                name = t.name
                description = t.description or name
                parameters = t.model_dump()["parameters"]
            declarations.append(
                {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "OBJECT",
                        "properties": parameters["properties"],
                        "required": parameters.get("required", []),
                    },
                }
            )
        return [{"function_declarations": declarations}]

    def record_resumption_update(self, new_handle: str | None, resumable: bool) -> None:
        """Remember the restore point Gemini reported for the current session.

        Any update proves Gemini accepted the session's handle. A non-resumable
        update (sent mid tool call or mid generation) carries no handle; the previous
        handle is kept, since resuming from it loses only what came after it.
        """
        self._resumption_unconfirmed = False
        if resumable and new_handle:
            self._resumption_handle = new_handle
            self._resumption_handle_time = time.monotonic()

    async def connect(self) -> None:
        """Open a Gemini Live session, resuming the previous one when possible.

        The system instruction is always the configured instructions alone; the
        conversation is never replayed as text. With a usable resumption handle the
        server restores the previous session's context. A handle whose resumed
        session closed before Gemini confirmed it is treated as refused.

        A transient failure is retried with the same handle on the backoff schedule,
        so one 429, 503 or 1011 does not end a call. When Gemini refuses the handle,
        or every resume attempt failed transiently, one fresh session is tried.
        A permanent upgrade rejection (401, 403, 404 and other 4xx but 408 and 429)
        is raised at once, with no retry and no fresh session.

        This is the only retry: handle_messages and ConversationService call
        connect() once per reconnect and add none of their own. On the browser path
        one schedule can still follow another: when handle_messages gives up, its
        task ends and ConversationService's reconnect calls connect() again.

        The whole of connect(), retries and fresh fallback included, is bounded by
        _CONNECT_DEADLINE_SECONDS; an attempt still running at the deadline is
        cancelled, leaving no session open.

        Raises:
            ConnectionClosed, InvalidStatus, OSError: No session could be opened.
                The handle is kept unless Gemini refused it, so a later connect can
                still resume.
            TimeoutError: The deadline passed first; the handle is kept.
        """
        if self._resumption_unconfirmed:
            logger.warning(
                "Gemini: the resumed session closed before Gemini confirmed it, starting fresh"
            )
            self._resumption_handle = None

        deadline = asyncio.timeout(_CONNECT_DEADLINE_SECONDS)
        try:
            async with deadline:
                handle = await self._open_resumed_or_fresh_session(self._resumption_handle)
        except TimeoutError:
            # websockets' own open timeout is a TimeoutError too; only ours is logged here.
            if deadline.expired():
                logger.error(
                    "Gemini: no session opened within {} s, giving up", _CONNECT_DEADLINE_SECONDS
                )
            raise

        self._resumption_unconfirmed = handle is not None
        self._replay_audio_after = self._resumption_handle_time if handle is not None else None
        self._session_version += 1

    async def _open_resumed_or_fresh_session(self, handle: str | None) -> str | None:
        """Open a session with `handle`, falling back to one fresh attempt.

        Returns the handle the open session was resumed from, or None for a fresh one.
        """
        try:
            await self._open_session_retrying(handle)
            return handle
        except _CONNECT_ERRORS as error:
            if handle is None or _is_permanent_upgrade_failure(error):
                raise
            if _is_resumption_refusal(error):
                logger.warning("Gemini: resumption handle refused ({}), starting fresh", error)
                self._resumption_handle = None
            else:
                logger.warning(
                    "Gemini: resuming still failing after retries ({}), trying a fresh session",
                    error,
                )
        await self._open_session(None)
        # The fresh session is a new conversation; the old handle no longer matches it.
        self._resumption_handle = None
        return None

    async def _open_session_retrying(self, resumption_handle: str | None) -> None:
        """Open a session, retrying transient failures on the backoff schedule.

        A refusal of the setup, or a permanent upgrade rejection, is raised at once:
        the same request would be rejected again. Once the schedule is spent, the
        last transient error is raised. Only the session with the caller's handle is
        retried; the fresh fallback in _open_resumed_or_fresh_session is a single
        attempt.
        """
        for backoff_seconds in (*_CONNECT_RETRY_BACKOFF_SECONDS, None):
            try:
                await self._open_session(resumption_handle)
                return
            except _CONNECT_ERRORS as error:
                if (
                    backoff_seconds is None
                    or _is_resumption_refusal(error)
                    or _is_permanent_upgrade_failure(error)
                ):
                    raise
                logger.warning(
                    "Gemini: connect failed transiently ({}), retrying in {} s",
                    error,
                    backoff_seconds,
                )
                await asyncio.sleep(backoff_seconds)

    async def _open_session(self, resumption_handle: str | None) -> None:
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            # None leaves the model's own default in place.
            temperature=self.temperature,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)
                )
            ),
            system_instruction=types.Content(parts=[types.Part(text=self.instructions)]),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
            ),
            session_resumption=types.SessionResumptionConfig(handle=resumption_handle),
        )
        if self.tools:
            config.tools = self.tools

        logger.info(
            "Gemini: connecting model={}, voice={}, resuming={}, tools={}",
            self.model,
            self.voice,
            resumption_handle is not None,
            [d["name"] for t in self.tools for d in t.get("function_declarations", [])],
        )
        session_cm = self._genai_client.aio.live.connect(model=self.model, config=config)
        try:
            session = await session_cm.__aenter__()
        except Exception as e:
            reason = getattr(getattr(e, "rcvd", None), "reason", None)
            code = getattr(getattr(e, "rcvd", None), "code", None)
            logger.error("Gemini: connection failed — code={}, reason={}, exc={}", code, reason, e)
            raise
        # Assigned only once entered: a failed or cancelled __aenter__ (the connect
        # deadline) leaves nothing for close() to exit, and the SDK's context closes
        # its own websocket when cancelled inside it.
        self._session_cm, self._session = session_cm, session
        logger.info("Gemini Live connected: model={}, voice={}", self.model, self.voice)

    async def close(self) -> None:
        """Close the Gemini Live session. Protected by a lock to prevent races."""
        async with self._close_lock:
            if self._session_cm:
                self._session = None  # stop send_audio immediately
                cm, self._session_cm = self._session_cm, None
                try:
                    await cm.__aexit__(None, None, None)
                except Exception as e:
                    logger.warning(f"Gemini: error closing session: {e}")

    async def handle_messages(self) -> None:
        """Receive Gemini messages, reopening the session when Gemini closes it.

        The voice-call path runs this once with no reconnect of its own, so a
        connection closed by Gemini (after a go_away or otherwise) is reopened here,
        resumed through connect(). Browser callers then get the buffered audio
        replayed; Twilio audio (send_audio) is not buffered, so there is nothing to
        replay for a call. The task stays alive meanwhile, so ConversationService's
        own reconnect (which fires only when this task ends) never reopens the same
        close a second time.

        Returns, closing the session, when it is cancelled, when receiving fails for
        a reason other than a closed connection, when reopening fails, when the
        session was closed locally, or after _MAX_RECONNECTS_WITHOUT_A_MESSAGE
        reconnects in a row whose sessions closed without delivering a message.
        """
        logger.info("Gemini: Message handler started.")
        reconnects_without_a_message = 0
        try:
            while True:
                session = self._session
                message_count = await self._receive_until_closed(session)
                if self._session is not session:
                    logger.info("Gemini: session closed locally, message handler stops")
                    return
                if message_count:
                    reconnects_without_a_message = 0
                elif reconnects_without_a_message >= _MAX_RECONNECTS_WITHOUT_A_MESSAGE:
                    logger.warning(
                        "Gemini: {} sessions in a row closed before any message, not reopening",
                        reconnects_without_a_message + 1,
                    )
                    return
                else:
                    reconnects_without_a_message += 1
                await self.close()
                self.server_event_handler.reset()
                await self.connect()
                await self.replay_audio_buffer()
                logger.info("Gemini: session reopened after a server close")
        except asyncio.CancelledError:
            logger.info("Gemini: handle_messages cancelled")
        except Exception as e:
            logger.exception("Gemini: handle_messages stopped: {}", e)
        finally:
            await self.close()

    async def _receive_until_closed(self, session) -> int:
        """Dispatch every message of one session until its connection closes.

        google-genai 1.19 ends receive() after every turn_complete although the
        session stays open, so it is called again for each turn; only the
        websocket's ConnectionClosed marks the end. Returns the number of messages
        received. Any other receive error propagates.
        """
        message_count = 0
        try:
            while True:
                async for response in session.receive():
                    message_count += 1
                    signal_fields = [
                        field
                        for field in ("tool_call", "go_away", "session_resumption_update")
                        if getattr(response, field, None) is not None
                    ]
                    if signal_fields:
                        logger.debug("Gemini msg #{}: {}", message_count, signal_fields)
                    if response.go_away is not None:
                        # Gemini closes the connection when time_left runs out; that
                        # close is what triggers the resumed reconnect.
                        logger.warning("Gemini: go_away — time_left={}", response.go_away.time_left)
                    try:
                        await self.server_event_handler.handle_event(response)
                    except Exception as e:
                        logger.exception("Gemini: Error processing message: {}", e)
        except ConnectionClosed as closed:
            logger.info(
                "Gemini: session closed after {} messages (code={}, reason={})",
                message_count,
                closed.rcvd.code if closed.rcvd else None,
                closed.rcvd.reason if closed.rcvd else None,
            )
        return message_count

    async def send_audio(self, ulaw8k_b64: str) -> None:
        """
        Accept base64-encoded µ-law 8kHz audio from Twilio and forward to Gemini
        as PCM 16kHz (the format Gemini Live expects).
        """
        if self._session is None:
            logger.warning("Gemini: session is closed, dropping audio chunk")
            return
        ulaw_bytes = base64.b64decode(ulaw8k_b64)
        pcm_8k = audioop.ulaw2lin(ulaw_bytes, 2)
        pcm_16k, self._resample_state_in = audioop.ratecv(
            pcm_8k, 2, 1, 8000, 16000, self._resample_state_in
        )
        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm_16k, mime_type="audio/pcm;rate=16000")
        )

    async def process_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Process incoming message from the frontend WebSocket."""
        return await self.client_event_handler.handle_event(data=message)

    async def send_conversation_item_to_server(self, text: str) -> None:
        """Send a user text message to Gemini (used in LISTEN wake-word mode and
        the frontend's typed-message path, see GeminiClientEventHandler)."""
        if self._session is None:
            logger.warning("Gemini: session is closed, dropping text message")
            return
        await self._session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=text)],
            ),
            turn_complete=True,
        )

    async def request_response(self, data: dict | None = None) -> None:
        """Gemini operates with automatic VAD — no explicit response trigger needed."""

    async def on_stream_start(self) -> None:
        """Twilio stream started — Gemini starts automatically, no action needed."""

    async def replay_audio_buffer(self) -> None:
        """Replay the rolling audio buffer to the new session after a reconnect.

        A resumed session already holds the conversation up to its handle, so only
        audio buffered after that handle was stored is replayed; a fresh session
        starts from the instructions alone and gets the whole buffer. No
        audio_stream_end is sent — live audio continues after the buffer and
        Gemini's VAD detects end-of-speech naturally.
        """
        if not self._audio_rolling_buffer or self._session is None:
            return
        chunks = [
            chunk
            for buffered_at, chunk in self._audio_rolling_buffer
            if self._replay_audio_after is None or buffered_at > self._replay_audio_after
        ]
        logger.info("Gemini: replaying {} buffered audio chunks to new session", len(chunks))
        for chunk in chunks:
            await self._session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )
        self._audio_rolling_buffer.clear()

    async def call_tool(self, call_id: str, tool_name: str, tool_arguments: dict[str, Any]) -> None:
        """Execute a tool via ToolManagerService and send the result back to Gemini.

        Spawned as a background task by _handle_tool_call so the receive loop
        is not blocked while the tool executes.  A session-version guard ensures
        the response is discarded if a reconnect happened during execution.
        """
        session_version = self._session_version
        try:
            tool_result = await self.tool_manager_service.execute(
                connection_key=self.connection_key,
                tool_name=tool_name,
                call_arguments=tool_arguments,
            )
            result_str = str(tool_result)
        except Exception as e:
            correlation_id = new_error_correlation_id()
            logger.exception(
                f"Gemini: Tool execution failed [correlation_id={correlation_id}]: {e}"
            )
            result_str = build_public_error_message(
                PublicErrorMessage.TOOL_EXECUTION_FAILED, correlation_id
            )

        if self._session is None:
            logger.warning(
                f"Gemini: session is closed, dropping tool response "
                f"(tool={tool_name}, call_id={call_id})"
            )
            return

        if self._session_version != session_version:
            logger.warning(
                f"Gemini: session was replaced during tool execution, dropping response "
                f"(tool={tool_name}, call_id={call_id})"
            )
            return

        try:
            await self._session.send_tool_response(
                function_responses=[
                    types.FunctionResponse(
                        id=call_id,
                        name=tool_name,
                        response={"result": result_str},
                    )
                ]
            )
        except Exception as e:
            logger.warning(
                f"Gemini: send_tool_response failed (session may have closed): "
                f"tool={tool_name}, call_id={call_id}, err={e}"
            )
