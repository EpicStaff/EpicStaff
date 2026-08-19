from typing import Dict
import json
import asyncio
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
    manager_host=settings.MANAGER_HOST,
    manager_port=settings.MANAGER_PORT,
)
elevenlabs_agent_provisioner = ElevenLabsAgentProvisioner(redis_service=redis_service)
factory = RealtimeAgentClientFactory(
    elevenlabs_agent_provisioner=elevenlabs_agent_provisioner
)
transcription_client_factory = TranscriptionClientFactory()


# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


connection_repository = ConnectionRepository(
    ttl_seconds=settings.CONNECTION_KEY_TTL_SECONDS
)

# ---------------------------------------------------------------------------
# Per-channel config cache  (keyed by channel token, TTL=60s)
# ---------------------------------------------------------------------------
_channel_cache: dict[str, tuple[dict, float]] = {}
_CHANNEL_TTL = 60.0

# Legacy global voice settings cache (kept for backward-compat /voice route)
_voice_settings_cache: dict | None = None
_voice_settings_cache_time: float = 0.0
_VOICE_SETTINGS_TTL = 60.0


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
                    f"[channel_config] loaded: agent_id={data.get('realtime_agent')} twilio={data.get('twilio')}"
                )
                return data
            else:
                logger.warning(
                    f"[channel_config] request failed: {r.status_code} {r.text}"
                )
    except Exception as e:
        logger.exception(f"[channel_config] exception fetching config: {e}")
    return {}


async def get_voice_settings() -> dict:
    """DEPRECATED: fetch global VoiceSettings singleton (for legacy /voice route)."""
    global _voice_settings_cache, _voice_settings_cache_time
    now = asyncio.get_event_loop().time()
    if (
        _voice_settings_cache is None
        or (now - _voice_settings_cache_time) > _VOICE_SETTINGS_TTL
    ):
        try:
            url = settings.INIT_API_URL.replace("init-realtime", "voice-settings")
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers={"Host": "localhost", "X-API-Key": settings.DJANGO_API_KEY},
                    timeout=5.0,
                )
                if r.is_success:
                    _voice_settings_cache = r.json()
                    _voice_settings_cache_time = now
                    logger.info(f"Voice settings loaded: {_voice_settings_cache}")
                else:
                    logger.warning(
                        f"Voice settings request failed: {r.status_code} {r.text}"
                    )
        except Exception as e:
            logger.warning(f"Could not fetch voice settings from Django: {e}")
    return _voice_settings_cache or {}


async def voice_settings_invalidation_listener():
    """Listen for voice settings changes and invalidate the local cache."""
    global _voice_settings_cache, _voice_settings_cache_time

    svc = RedisService(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
    )
    await svc.connect()
    pubsub = await svc.async_subscribe("voice_settings:invalidate")
    logger.info("Subscribed to channel 'voice_settings:invalidate'")

    async for message in pubsub.listen():
        if message["type"] == "message":
            _voice_settings_cache = None
            _voice_settings_cache_time = 0.0
            # Also clear per-channel cache when channel config changes
            token = message.get("data", "")
            if token:
                _channel_cache.pop(token, None)
                logger.info(f"Channel cache invalidated for token {token}")
            else:
                _channel_cache.clear()
                logger.info("Voice settings cache invalidated (all channels cleared)")


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
    asyncio.create_task(voice_settings_invalidation_listener())


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


async def _resolve_channel_agent(channel_token: str) -> tuple[int | None, dict]:
    """Fetch channel config and return (agent_id, channel_data)."""
    channel = await get_channel_config(channel_token)
    agent_id = channel.get("realtime_agent")
    return agent_id, channel


async def _twilio_voice_webhook(
    request: Request, auth_token: str | None, voice_stream_url: str
) -> Response:
    """Shared logic for both old and new Twilio voice webhook handlers."""
    logger.info(
        f"[voice_webhook] auth_token present={bool(auth_token)} voice_stream_url={voice_stream_url}"
    )
    logger.debug(f"[voice_webhook] headers={dict(request.headers)}")

    if auth_token:
        signature = request.headers.get("X-Twilio-Signature", "")
        proto = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("x-forwarded-host") or request.headers.get(
            "host", ""
        )
        path = request.url.path
        query = f"?{request.url.query}" if request.url.query else ""
        url = f"{proto}://{host}{path}{query}"
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
        logger.warning("[voice_webhook] no auth_token — skipping signature validation")

    if not voice_stream_url:
        logger.error("[voice_webhook] no voice_stream_url configured")
        raise HTTPException(status_code=503, detail="No voice stream URL configured")

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{voice_stream_url}" />
  </Connect>
</Response>"""
    logger.info(f"[voice_webhook] returning TwiML with stream url={voice_stream_url}")
    return Response(content=twiml, media_type="application/xml")


async def _voice_stream_handler(
    twilio_ws: WebSocket,
    agent_id: int | None,
    auth_token: str | None,
    agent_definition_id: int | None = None,
) -> None:
    """Shared logic for voice stream WebSocket handlers.

    agent_id / agent_definition_id are resolved by the caller (either from the
    channel-token config or, for the deprecated /voice/stream route, from the
    global Voice Settings singleton) before this handler is invoked.
    """
    await twilio_ws.accept()
    logger.info("Twilio MediaStream WebSocket accepted")

    # Read the first Twilio message (connected / start) to get stream_sid
    first_msg = None
    try:
        raw = await asyncio.wait_for(twilio_ws.receive_text(), timeout=5.0)
        first_msg = json.loads(raw)
        if first_msg.get("event") == "connected":
            raw = await asyncio.wait_for(twilio_ws.receive_text(), timeout=5.0)
            first_msg = json.loads(raw)
        if first_msg.get("event") == "start":
            logger.info(f"Twilio stream started: agent_id={agent_id}")
    except Exception as e:
        logger.warning(f"Could not read Twilio start event: {e}")
        first_msg = None

    # Call Django init-realtime with the resolved agent_id / agent_definition_id
    audio_config = {
        "input_audio_format": "g711_ulaw",
        "output_audio_format": "g711_ulaw",
    }
    if agent_definition_id:
        init_realtime_payload = {
            "agent_definition_id": agent_definition_id,
            "config": audio_config,
        }
    else:
        init_realtime_payload = {
            "agent_id": agent_id,
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
    )
    await service.execute()


@app.post("/voice/{channel_token}")
async def twilio_voice_webhook_channel(channel_token: str, request: Request):
    """
    Twilio calls this on incoming call (channel-token routing).
    Returns TwiML directing audio to /voice/{channel_token}/stream.
    """
    logger.info(f"[voice/{channel_token}] POST received from {request.client.host}")

    agent_id, channel = await _resolve_channel_agent(channel_token)
    logger.info(
        f"[voice/{channel_token}] resolved agent_id={agent_id} channel_keys={list(channel.keys())}"
    )

    if not agent_id:
        logger.error(f"[voice/{channel_token}] no agent assigned — returning 404")
        raise HTTPException(
            status_code=404, detail="Channel not found or no agent assigned"
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
    else:
        # NOTE: `live_url` is intentionally NOT used here. It belongs to the
        # generic webhook-trigger microservice and already carries a
        # `/webhooks/{path}` prefix (e.g. `/webhooks/twilio`). nginx's
        # `^~ /webhooks/` location block would intercept a WS URL built from
        # it and route it to the unrelated `webhook` stub service, which has
        # no WebSocket handler — breaking the Twilio Media Stream handshake.
        voice_stream_url = (
            settings.VOICE_STREAM_URL.replace(
                "/voice/stream", f"/voice/{channel_token}/stream"
            )
            if settings.VOICE_STREAM_URL
            else ""
        )

    logger.info(f"[voice/{channel_token}] voice_stream_url={voice_stream_url}")
    return await _twilio_voice_webhook(request, auth_token, voice_stream_url)


@app.websocket("/voice/{channel_token}/stream")
async def voice_stream_channel(channel_token: str, twilio_ws: WebSocket):
    """Twilio MediaStream WebSocket (channel-token routing)."""
    agent_id, channel = await _resolve_channel_agent(channel_token)
    if not agent_id:
        logger.error(f"No agent for channel token {channel_token}")
        await twilio_ws.close()
        return
    await _voice_stream_handler(twilio_ws, agent_id, auth_token=None)


# ---------------------------------------------------------------------------
# Legacy Twilio routes  (kept for backward compatibility)
# ---------------------------------------------------------------------------


@app.post("/voice")
async def twilio_voice_webhook(request: Request):
    """DEPRECATED: use /voice/{channel_token} instead."""
    vs = await get_voice_settings()
    auth_token = vs.get("twilio_auth_token")
    voice_stream_url = vs.get("voice_stream_url") or settings.VOICE_STREAM_URL
    return await _twilio_voice_webhook(request, auth_token, voice_stream_url)


@app.websocket("/voice/stream")
async def voice_stream(twilio_ws: WebSocket):
    """DEPRECATED: use /voice/{channel_token}/stream instead."""
    vs = await get_voice_settings()
    agent_id = vs.get("voice_agent")
    agent_definition_id = vs.get("voice_agent_definition")
    if not agent_id and not agent_definition_id:
        logger.error("No voice agent configured in Voice Settings")
        await twilio_ws.close()
        return
    await _voice_stream_handler(
        twilio_ws,
        agent_id,
        auth_token=None,
        agent_definition_id=agent_definition_id,
    )
