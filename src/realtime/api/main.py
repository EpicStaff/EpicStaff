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
from twilio.request_validator import RequestValidator
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


connection_repository = ConnectionRepository()

_voice_settings_cache: dict | None = None
_voice_settings_cache_time: float = 0.0
_VOICE_SETTINGS_TTL = 60.0


async def get_voice_settings() -> dict:
    global _voice_settings_cache, _voice_settings_cache_time
    now = asyncio.get_event_loop().time()
    if (
        _voice_settings_cache is None
        or (now - _voice_settings_cache_time) > _VOICE_SETTINGS_TTL
    ):
        try:
            url = settings.INIT_API_URL.replace("init-realtime", "voice-settings")
            async with httpx.AsyncClient() as client:
                r = await client.get(url, headers={"Host": "localhost"}, timeout=5.0)
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
            logger.info("Voice settings cache invalidated")


async def _run_forever(coro_fn, name: str, restart_delay: float = 2.0):
    """Run a coroutine, restarting it if it crashes."""
    while True:
        try:
            await coro_fn()
            logger.warning(f"{name} exited unexpectedly, restarting in {restart_delay}s")
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
                logger.debug(connection_repository)
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

    connection_key = realtime_agent_chat_data.connection_key

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


@app.post("/voice")
async def twilio_voice_webhook(request: Request):
    """Twilio calls this on incoming call. Returns TwiML directing audio to /voice/stream."""
    vs = await get_voice_settings()
    auth_token = vs.get("twilio_auth_token")
    if auth_token:
        validator = RequestValidator(auth_token)
        signature = request.headers.get("X-Twilio-Signature", "")
        proto = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("x-forwarded-host") or request.headers.get(
            "host", ""
        )
        path = request.url.path
        query = f"?{request.url.query}" if request.url.query else ""
        url = f"{proto}://{host}{path}{query}"
        form_data = dict(await request.form())
        logger.debug(f"Twilio validation URL: {url}")
        if not validator.validate(url, form_data, signature):
            logger.warning(
                f"Invalid Twilio signature from {request.client.host}, url={url}"
            )
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    voice_stream_url = vs.get("voice_stream_url") or settings.VOICE_STREAM_URL
    if not voice_stream_url:
        logger.error("No voice stream URL configured (ngrok not set up)")
        raise HTTPException(status_code=503, detail="No voice stream URL configured")

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{voice_stream_url}" />
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.websocket("/voice/stream")
async def voice_stream(twilio_ws: WebSocket):
    """Twilio MediaStream WebSocket. Bridges audio directly to AI Realtime API."""
    await twilio_ws.accept()
    logger.info("Twilio MediaStream WebSocket accepted")

    # 1. Resolve agent_id from Voice Settings
    vs = await get_voice_settings()
    agent_id = vs.get("voice_agent")
    if not agent_id:
        logger.error("No voice agent configured in Voice Settings")
        await twilio_ws.close()
        return

    # 2. Read the first Twilio message (connected / start) to get stream_sid
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

    # 2. Call Django init-realtime with the resolved agent_id
    async with httpx.AsyncClient() as http_client:
        try:
            resp = await http_client.post(
                settings.INIT_API_URL,
                headers={"Host": "localhost"},
                json={
                    "agent_id": agent_id,
                    "config": {
                        "input_audio_format": "g711_ulaw",
                        "output_audio_format": "g711_ulaw",
                    },
                },
                timeout=10.0,
            )
            if resp.status_code >= 400:
                logger.error(f"Init realtime failed: {resp.status_code} {resp.text}")
                await twilio_ws.close()
                return
            conn_key = resp.json().get("connection_key")
            logger.info(f"Init realtime response: status={resp.status_code} conn_key={conn_key}")
        except Exception as e:
            logger.error(f"Failed to init realtime session: {e}")
            await twilio_ws.close()
            return

    # 3. Wait for Redis listener to store agent config (delivered asynchronously)
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

    # 4. Build instructions and hand off to VoiceCallService
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
        initial_message=first_msg,
    )
    await service.execute()
