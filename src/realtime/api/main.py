from typing import Dict
import json
import asyncio
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from xml.sax.saxutils import quoteattr
import httpx
from loguru import logger
from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    Response,
    Request,
    HTTPException,
)
from fastapi.middleware.cors import CORSMiddleware
from src.shared.models import RealtimeAgentChatData
from application.conversation_service import ConversationService
from application.voice_call_service import VoiceCallService
from application.tool_manager_service import ToolManagerService
from infrastructure.messaging.python_code_executor_service import (
    PythonCodeExecutorService,
)
from infrastructure.messaging.redis_service import RedisService
from infrastructure.persistence.connection_repository import ConnectionRepository
from infrastructure.persistence.stream_token_repository import StreamTokenRepository
from infrastructure.providers.elevenlabs.elevenlabs_agent_provisioner import (
    ElevenLabsAgentProvisioner,
)
from infrastructure.providers.factory import RealtimeAgentClientFactory
from infrastructure.summarization.openai_summarization_client import (
    OpenaiSummarizationClient,
)
from infrastructure.transcription.transcription_client_factory import (
    TranscriptionClientFactory,
)
from utils.instructions_concatenator import generate_instruction
from core.config import settings
from utils.auth import introspect_token
from utils.twilio_signature import validate_twilio_signature


from infrastructure.persistence.database import get_db, engine
from infrastructure.persistence.db_models import Base
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession


app = FastAPI()
redis_service = RedisService(
    host=settings.REDIS_HOST, port=settings.REDIS_PORT, password=settings.REDIS_PASSWORD
)
python_code_executor_service = PythonCodeExecutorService(redis_service=redis_service)
tool_manager_service = ToolManagerService(
    redis_service=redis_service,
    python_code_executor_service=python_code_executor_service,
    knowledge_search_get_channel=settings.KNOWLEDGE_SEARCH_GET_CHANNEL,
    knowledge_search_response_channel=settings.KNOWLEDGE_SEARCH_RESPONSE_CHANNEL,
)
elevenlabs_agent_provisioner = ElevenLabsAgentProvisioner(redis_service=redis_service)
factory = RealtimeAgentClientFactory(
    elevenlabs_agent_provisioner=elevenlabs_agent_provisioner
)
transcription_client_factory = TranscriptionClientFactory()


# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


connection_repository = ConnectionRepository(
    ttl_seconds=settings.CONNECTION_KEY_TTL_SECONDS
)
stream_token_repository = StreamTokenRepository(
    ttl_seconds=settings.STREAM_TOKEN_TTL_SECONDS
)

# ---------------------------------------------------------------------------
# Per-channel config cache  (keyed by channel token, TTL=60s)
# ---------------------------------------------------------------------------
_channel_cache: dict[str, tuple[dict, float]] = {}
_CHANNEL_TTL = 60.0


async def get_channel_config(channel_token: str) -> dict:
    """Fetch TwilioChannel config for the given UUID token (cached, TTL=60s)."""
    now = asyncio.get_event_loop().time()
    cached = _channel_cache.get(channel_token)
    if cached and (now - cached[1]) < _CHANNEL_TTL:
        logger.debug(f"[channel_config] cache hit for token={channel_token}")
        return cached[0]

    # Dedicated by-token lookup action (RealtimeChannelViewSet.lookup_by_token) —
    # unscoped by org, API-key-only. This request comes from Twilio via us with
    # no logged-in user and no org context, so it cannot use the normal
    # org-scoped list endpoint (that 400s with org_context_required).
    url = f"{settings.DJANGO_API_BASE_URL}/realtime-channels/lookup-by-token/"
    logger.info(f"[channel_config] fetching from Django: {url}?token={channel_token}")
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url,
                params={"token": channel_token},
                headers={"Host": "localhost", "X-API-Key": settings.DJANGO_API_KEY},
                timeout=5.0,
            )
            logger.debug(
                f"[channel_config] Django response: status={r.status_code} body={r.text[:300]}"
            )
            if r.is_success:
                data = r.json()
                if not isinstance(data, dict):
                    data = {}
                _channel_cache[channel_token] = (data, now)
                logger.info(
                    f"[channel_config] loaded: agent_definition_id={data.get('realtime_agent_definition')} "
                    f"legacy_realtime_agent={data.get('realtime_agent')} "
                    f"twilio={data.get('twilio')}"
                )
                return data
            else:
                logger.warning(
                    f"[channel_config] request failed: {r.status_code} {r.text}"
                )
    except Exception as e:
        logger.exception(f"[channel_config] exception fetching config: {e}")
    return {}


async def _run_forever(coro_fn, name: str, restart_delay: float = 2.0):
    """Run a coroutine, restarting it if it crashes."""
    while True:
        try:
            await coro_fn()
            logger.warning(
                f"{name} exited unexpectedly, restarting in {restart_delay}s"
            )
        except Exception as e:
            logger.error(f"{name} crashed: {e}, restarting in {restart_delay}s")
        await asyncio.sleep(restart_delay)


async def redis_listener():
    """Listen to Redis channel and store connection data."""

    redis_service = RedisService(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
    )
    await redis_service.connect()
    logger.info("redis_listener: connected to Redis")

    pubsub = await redis_service.async_subscribe(
        settings.REALTIME_AGENTS_SCHEMA_CHANNEL
    )
    logger.info(f"Subscribed to channel '{settings.REALTIME_AGENTS_SCHEMA_CHANNEL}'")

    async for message in pubsub.listen():
        if message["type"] == "message":
            try:
                data = json.loads(message["data"])
                realtime_agent_chat_data = RealtimeAgentChatData(**data)
                connection_repository.save_connection(
                    realtime_agent_chat_data.connection_key, realtime_agent_chat_data
                )

                logger.info(
                    f"Saved connection: {realtime_agent_chat_data.connection_key}"
                )

            except Exception as e:
                logger.error(f"Error processing embedding: {e}")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.on_event("startup")
async def startup_event():
    """Start Redis listener and init DB on FastAPI startup."""
    await init_db()

    asyncio.create_task(_run_forever(redis_listener, "redis_listener"))


# Store active connections and their handlers
connections: Dict[WebSocket, tuple] = {}


@app.websocket("/realtime/")
async def root(
    websocket: WebSocket,
    model: str | None = None,
    connection_key: str | None = None,
    db_session: AsyncSession = Depends(get_db),
):
    token = websocket.query_params.get("token")
    logger.info(
        f"WebSocket connect attempt path={websocket.url.path} "
        f"query_params={websocket.query_params}"
    )
    if not token:
        logger.warning("WebSocket auth missing token")
        await websocket.close(code=1008)
        return

    user_info = introspect_token(token)
    if not user_info:
        logger.warning("WebSocket auth failed: token invalid or introspection failed")
        await websocket.close(code=1008)
        return

    if connection_key is None:
        logger.error("Invalid connection_key. Connection refused!")
        await websocket.close(code=1008)
        return
    realtime_agent_chat_data: RealtimeAgentChatData = (
        connection_repository.get_connection(connection_key=connection_key)
    )

    if realtime_agent_chat_data is None:
        logger.warning(f"Connection not found for key: {connection_key}")
        await websocket.close(code=1011)
        return

    # Fail fast, unconditionally (even for superadmin, whose bypass below
    # never evaluates realtime_agent_chat_data.org_id at all): org_id is a
    # required field, but if any construction path (current or future) ever
    # produces a payload missing it — e.g. a stale cache, a partially-built
    # object, or a new call site that forgot to set it — we want a clear
    # rejection here, not a raw AttributeError deep inside provider client
    # construction (factory.create) or an unscoped session later on.
    if getattr(realtime_agent_chat_data, "org_id", None) is None:
        logger.error(
            f"WebSocket auth rejected: connection_key={connection_key} has no "
            "org_id on its RealtimeAgentChatData payload — refusing to start "
            "an unscoped realtime session."
        )
        await websocket.close(code=1011)
        return

    if not user_info.get("is_superadmin") and realtime_agent_chat_data.org_id not in (
        user_info.get("org_ids") or []
    ):
        logger.warning(
            f"WebSocket auth rejected: user {user_info.get('user_id')} has no "
            f"membership in org {realtime_agent_chat_data.org_id} for "
            f"connection_key={connection_key}"
        )
        await websocket.close(code=1008)
        return

    connection_key = realtime_agent_chat_data.connection_key

    connection_repository.delete_connection(connection_key)

    instructions = generate_instruction(
        role=realtime_agent_chat_data.role,
        goal=realtime_agent_chat_data.goal,
        backstory=realtime_agent_chat_data.backstory,
    )

    summ_client = OpenaiSummarizationClient(
        api_key=realtime_agent_chat_data.rt_api_key,
        base_url=realtime_agent_chat_data.rt_base_url,
    )
    service = ConversationService(
        client_websocket=websocket,
        realtime_agent_chat_data=realtime_agent_chat_data,
        instructions=instructions,
        tool_manager_service=tool_manager_service,
        connections=connections,
        factory=factory,
        summ_client=summ_client,
        transcription_client_factory=transcription_client_factory,
    )

    websocket.state.user = user_info
    await service.execute()


@app.websocket("/ht")
async def healthcheck_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Message received: {data}")
    except WebSocketDisconnect:
        logger.info("Client disconnected")


# ---------------------------------------------------------------------------
# Channel-token-based Twilio routes  (new, preferred)
# ---------------------------------------------------------------------------


async def _resolve_channel_agent(
    channel_token: str,
) -> tuple[int | None, dict]:
    """Fetch channel config and return (agent_definition_id, channel_data).

    `realtime_agent` (the legacy staff agent) is intentionally not read here:
    Django removed the legacy staff-agent path, so `realtime_agent_definition`
    is the only destination init-realtime can still accept.
    """
    channel = await get_channel_config(channel_token)
    agent_definition_id = channel.get("realtime_agent_definition")
    return agent_definition_id, channel


def _describe_missing_agent(channel: dict) -> str:
    """Explain why a channel has no usable agent destination, for logs and
    error responses. A channel still bound only to the removed legacy staff
    agent needs different remediation (re-point it at an agent definition)
    than one that was never assigned an agent at all — callers should not
    collapse the two into one generic message."""
    legacy_agent_id = channel.get("realtime_agent")
    if legacy_agent_id:
        return (
            f"channel is still bound to removed legacy staff agent "
            f"(realtime_agent={legacy_agent_id}) — re-point it at an agent "
            "definition (realtime_agent_definition)"
        )
    return "channel has no agent assigned (realtime_agent_definition is not set)"


def _append_stream_token(voice_stream_url: str, stream_token: str) -> str:
    """Append `?stream_token=<token>` (preserving any existing query params)
    to the Media Stream WS URL embedded in the TwiML `<Stream url="...">`.

    NOTE: this is kept only as a harmless, best-effort fallback. Confirmed in
    production (EST voice-call regression, 2026-08): Twilio does NOT forward
    query parameters on the `<Stream>` `url` attribute to the actual Media
    Stream WebSocket connection — the TwiML response embeds the query string
    correctly, but it never arrives at the WS handler. The real, Twilio-
    blessed channel for auxiliary data like `stream_token` is the nested
    `<Parameter>` element (delivered in the `start` event's
    `customParameters`), built in `_twilio_voice_webhook` below. Do not rely
    on this query string alone for auth.
    """
    parsed = urlparse(voice_stream_url)
    query = parse_qsl(parsed.query)
    query.append(("stream_token", stream_token))
    return urlunparse(parsed._replace(query=urlencode(query)))


async def _twilio_voice_webhook(
    request: Request,
    auth_token: str | None,
    voice_stream_url: str,
    stream_token: str,
    base_url: str,
) -> Response:
    """Shared logic for both old and new Twilio voice webhook handlers."""
    logger.info(
        f"[voice_webhook] auth_token present={bool(auth_token)} voice_stream_url={voice_stream_url}"
    )
    logger.debug(f"[voice_webhook] headers={dict(request.headers)}")

    if auth_token:
        signature = request.headers.get("X-Twilio-Signature", "")
        base_url = (base_url or "").rstrip("/")
        if not base_url:
            logger.error(
                "[voice_webhook] no tunnel domain resolved for this channel's "
                "webhook_trigger -- cannot validate Twilio signature (fail "
                "closed, no env-var fallback)"
            )
            raise HTTPException(
                status_code=503,
                detail="No tunnel domain configured for this channel -- cannot validate Twilio signature",
            )
        path = request.url.path
        query = f"?{request.url.query}" if request.url.query else ""
        url = f"{base_url}{path}{query}"
        form_data = dict(await request.form())
        logger.debug(
            f"[voice_webhook] validating signature: url={url} form_data={form_data}"
        )
        valid = validate_twilio_signature(url, form_data, signature, auth_token)
        logger.info(f"[voice_webhook] signature valid={valid}")
        if not valid:
            logger.warning(
                f"[voice_webhook] invalid signature from {request.client.host}"
            )
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    else:
        logger.warning(
            "[voice_webhook] no auth_token — rejecting request (fail closed)"
        )
        raise HTTPException(status_code=503, detail="Twilio auth not configured")

    if not voice_stream_url:
        logger.error("[voice_webhook] no voice_stream_url configured")
        raise HTTPException(status_code=503, detail="No voice stream URL configured")

    voice_stream_url = _append_stream_token(voice_stream_url, stream_token)

    stream_url_attr = quoteattr(voice_stream_url)
    stream_token_attr = quoteattr(stream_token)
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url={stream_url_attr}>
      <Parameter name="stream_token" value={stream_token_attr} />
    </Stream>
  </Connect>
</Response>"""
    logger.info(f"[voice_webhook] returning TwiML with stream url={voice_stream_url}")
    return Response(content=twiml, media_type="application/xml")


async def _voice_stream_handler(
    twilio_ws: WebSocket,
    agent_definition_id: int,
    auth_token: str | None,
    stream_token: str | None = None,
    stream_bound_key: str | None = None,
) -> None:
    """Shared logic for voice stream WebSocket handlers.

    agent_definition_id is resolved by the caller from the channel-token
    config before this handler is invoked; callers are expected to have
    already rejected channels with no usable destination (see
    `_describe_missing_agent`) before calling this.

    Twilio's Media Stream WS leg carries no verifiable Twilio header (no
    `X-Twilio-Signature`), so authentication here is a short-lived, single-use
    `stream_token` minted by the paired (signature-validated) TwiML webhook and
    bound to the same route (`stream_bound_key` — the channel_token, or the
    legacy sentinel).

    Confirmed in production (2026-08 voice-call regression): Twilio does NOT
    forward the `?stream_token=...` query string embedded in the TwiML
    `<Stream url="...">` to this WebSocket connection — the query param never
    arrives here (`websocket.query_params` is empty) even though the TwiML
    response correctly contained it. The token now arrives (if at all) via
    the nested `<Parameter name="stream_token" value="...">` element, which
    Twilio delivers inside the first `start` event's `customParameters`. That
    means the token is not knowable until *after* the WebSocket handshake, so
    `.accept()` itself can no longer gate on it. Instead: accept the socket,
    read the `start` event, and validate immediately — closing before any
    Django `init-realtime` call, provider connection, or audio processing
    happens if the token is missing/invalid. This is a strictly later gate
    than the pre-accept ideal, but it still fully preserves the security
    intent: an unauthenticated caller never reaches a live media bridge or
    causes any side effect. The `stream_token` query param (if a caller
    happens to send one — e.g. direct test tooling) is still honoured as a
    fallback source.
    """
    await twilio_ws.accept()
    logger.info(
        "Twilio MediaStream WebSocket accepted (stream_token not yet validated)"
    )

    # Read the first Twilio message(s): `connected` (optional) then `start`,
    # which carries `customParameters` — see docstring above for why this is
    # now the primary source of `stream_token` instead of the query string.
    first_msg = None
    try:
        raw = await asyncio.wait_for(twilio_ws.receive_text(), timeout=5.0)
        first_msg = json.loads(raw)
        if first_msg.get("event") == "connected":
            raw = await asyncio.wait_for(twilio_ws.receive_text(), timeout=5.0)
            first_msg = json.loads(raw)
        if first_msg.get("event") == "start":
            logger.info(
                f"Twilio stream started: agent_definition_id={agent_definition_id}"
            )
    except Exception as e:
        logger.warning(f"Could not read Twilio start event: {e}")
        first_msg = None

    custom_params = ((first_msg or {}).get("start") or {}).get("customParameters") or {}
    param_token = custom_params.get("stream_token")
    effective_stream_token = param_token or stream_token
    token_source = (
        "start.customParameters"
        if param_token
        else ("query_param" if stream_token else "none")
    )

    if not stream_token_repository.consume(
        effective_stream_token, bound_key=stream_bound_key
    ):
        # `token_present` distinguishes "no token arrived by either channel"
        # from "we had a token but it didn't validate" (expired/reused/wrong
        # bound_key, or the in-memory StreamTokenRepository singleton lost
        # its state — e.g. a `--reload` process restart between the webhook
        # mint and this consume).
        logger.warning(
            f"Voice stream WS rejected: missing/invalid/expired/reused stream_token "
            f"(bound_key={stream_bound_key}, token_present={bool(effective_stream_token)}, "
            f"token_source={token_source})"
        )
        await twilio_ws.close(code=1008)
        return

    # Call Django init-realtime with the resolved agent_definition_id.
    audio_config = {
        "input_audio_format": "g711_ulaw",
        "output_audio_format": "g711_ulaw",
    }
    init_realtime_payload = {
        "agent_definition_id": agent_definition_id,
        "config": audio_config,
    }

    async with httpx.AsyncClient() as http_client:
        try:
            resp = await http_client.post(
                settings.INIT_API_URL,
                headers={"Host": "localhost", "X-API-Key": settings.DJANGO_API_KEY},
                json=init_realtime_payload,
                timeout=10.0,
            )
            if resp.status_code >= 400:
                logger.error(f"Init realtime failed: {resp.status_code} {resp.text}")
                await twilio_ws.close()
                return
            conn_key = resp.json().get("connection_key")
            logger.info(
                f"Init realtime response: status={resp.status_code} conn_key={conn_key}"
            )
        except Exception as e:
            logger.error(f"Failed to init realtime session: {e}")
            await twilio_ws.close()
            return

    # Wait for Redis listener to store agent config (delivered asynchronously)
    realtime_agent_chat_data = None
    for _ in range(20):  # up to 2 seconds
        realtime_agent_chat_data = connection_repository.get_connection(conn_key)
        if realtime_agent_chat_data:
            break
        await asyncio.sleep(0.1)

    if realtime_agent_chat_data is None:
        logger.error(f"No agent data found for connection_key={conn_key}")
        await twilio_ws.close()
        return

    # Same fail-fast as the browser /realtime/ path: org_id is required, but
    # refuse explicitly here rather than blow up later inside
    # factory.create()/save_realtime_session_item_to_db with a raw
    # AttributeError if it's ever missing.
    if getattr(realtime_agent_chat_data, "org_id", None) is None:
        logger.error(
            f"Twilio voice stream rejected: connection_key={conn_key} has no "
            "org_id on its RealtimeAgentChatData payload — refusing to start "
            "an unscoped realtime session."
        )
        await twilio_ws.close()
        return

    connection_repository.delete_connection(conn_key)

    instructions = generate_instruction(
        role=realtime_agent_chat_data.role,
        goal=realtime_agent_chat_data.goal,
        backstory=realtime_agent_chat_data.backstory,
    )
    service = VoiceCallService(
        twilio_ws=twilio_ws,
        realtime_agent_chat_data=realtime_agent_chat_data,
        instructions=instructions,
        tool_manager_service=tool_manager_service,
        connections=connections,
        factory=factory,
        django_api_base_url=settings.DJANGO_API_BASE_URL,
        django_api_key=settings.DJANGO_API_KEY,
        initial_message=first_msg,
        max_call_duration_seconds=settings.MAX_CALL_DURATION_SECONDS,
    )
    await service.execute()


@app.post("/voice/{channel_token}")
async def twilio_voice_webhook_channel(channel_token: str, request: Request):
    """
    Twilio calls this on incoming call (channel-token routing).
    Returns TwiML directing audio to /voice/{channel_token}/stream.
    """
    logger.info(f"[voice/{channel_token}] POST received from {request.client.host}")

    agent_definition_id, channel = await _resolve_channel_agent(channel_token)
    logger.info(
        f"[voice/{channel_token}] resolved agent_definition_id={agent_definition_id} "
        f"channel_keys={list(channel.keys())}"
    )

    if not agent_definition_id:
        reason = _describe_missing_agent(channel)
        logger.error(f"[voice/{channel_token}] {reason} — returning 404")
        raise HTTPException(
            status_code=404,
            detail=f"Channel not found or no agent assigned: {reason}",
        )

    twilio_cfg = channel.get("twilio") or {}
    auth_token = twilio_cfg.get("auth_token")
    webhook_trigger = twilio_cfg.get("webhook_trigger") or {}
    ngrok_cfg = webhook_trigger.get("ngrok_config") or {}
    live_url = webhook_trigger.get("live_url") or ""
    ngrok_domain = ngrok_cfg.get("domain") or ""
    logger.info(
        f"[voice/{channel_token}] twilio_cfg keys={list(twilio_cfg.keys())} ngrok_cfg={ngrok_cfg} live_url={live_url} ngrok_domain={ngrok_domain}"
    )

    if ngrok_domain:
        # Bare domain — the correct source for the Media Stream WS URL.
        voice_stream_url = f"wss://{ngrok_domain}/voice/{channel_token}/stream"
    elif live_url:
        parsed_live = urlparse(live_url)
        voice_stream_url = f"wss://{parsed_live.netloc}/voice/{channel_token}/stream"
    else:
        voice_stream_url = (
            settings.VOICE_STREAM_URL.replace(
                "/voice/stream", f"/voice/{channel_token}/stream"
            )
            if settings.VOICE_STREAM_URL
            else ""
        )

    logger.info(f"[voice/{channel_token}] voice_stream_url={voice_stream_url}")

    if live_url:
        parsed_live = urlparse(live_url)
        base_url = f"{parsed_live.scheme}://{parsed_live.netloc}"
    elif ngrok_domain:
        base_url = f"https://{ngrok_domain}"
    else:
        base_url = ""
    stream_token = stream_token_repository.mint(bound_key=channel_token)
    return await _twilio_voice_webhook(
        request, auth_token, voice_stream_url, stream_token, base_url
    )


@app.websocket("/voice/{channel_token}/stream")
async def voice_stream_channel(
    channel_token: str, twilio_ws: WebSocket, stream_token: str | None = None
):
    """Twilio MediaStream WebSocket (channel-token routing)."""
    agent_definition_id, channel = await _resolve_channel_agent(channel_token)
    if not agent_definition_id:
        logger.error(
            f"No agent for channel token {channel_token}: "
            f"{_describe_missing_agent(channel)}"
        )
        await twilio_ws.close(code=1008)
        return
    await _voice_stream_handler(
        twilio_ws,
        agent_definition_id,
        auth_token=None,
        stream_token=stream_token,
        stream_bound_key=channel_token,
    )
