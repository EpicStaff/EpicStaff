from typing import Dict
import json
import os
import sys
import asyncio
from loguru import logger
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv, find_dotenv
from models.request_models import RealtimeAgentChatData
from services.chat_executor import ChatExecutor
from services.python_code_executor_service import PythonCodeExecutorService
from services.redis_service import RedisService
from services.tool_manager_service import ToolManagerService
from utils.shorten import shorten_dict
from utils.instructions_concatenator import generate_instruction

if "--debug" in sys.argv:
    logger.info("RUNNING IN DEBUG MODE")
    load_dotenv(find_dotenv("debug.env"))
else:
    load_dotenv(find_dotenv(".env"))

from ai.agent.openai_realtime_agent_client import (
    OpenaiRealtimeAgentClient,
)

from services.redis_service import RedisService
from api.connection_repository import ConnectionRepository
from models.request_models import RealtimeAgentChatData
from ai.agent.openai_realtime_agent_client import (
    OpenaiRealtimeAgentClient,
)
from ai.transcription.realtime_transcription import (
    OpenaiRealtimeTranscriptionClient,
)


from db.database import get_db, engine
from models.db_models import Base
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

knowledge_search_get_channel = os.getenv(
    "KNOWLEDGE_SEARCH_GET_CHANNEL", "knowledge:search:get"
)
knowledge_search_response_channel = os.getenv(
    "KNOWLEDGE_SEARCH_RESPONSE_CHANNEL", "knowledge:search:response"
)
realtime_agents_schema_channel = os.getenv(
    "REALTIME_AGENTS_SCHEMA_CHANNEL", "realtime_agents:schema"
)

redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
redis_port = int(os.getenv("REDIS_PORT", 6379))
manager_host = os.getenv("MANAGER_HOST", "127.0.0.1")
manager_port = int(os.getenv("MANAGER_PORT", 8001))

app = FastAPI()
redis_service = RedisService(host=redis_host, port=redis_port)
python_code_executor_service = PythonCodeExecutorService(redis_service=redis_service)
tool_manager_service = ToolManagerService(
    redis_service=redis_service,
    python_code_executor_service=python_code_executor_service,
    knowledge_search_get_channel=knowledge_search_get_channel,
    knowledge_search_response_channel=knowledge_search_response_channel,
    manager_host=manager_host,
    manager_port=manager_port,
)


# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


connection_repository = ConnectionRepository()


async def redis_listener():
    """Listen to Redis channel and store connection data."""

    redis_service = RedisService(host=redis_host, port=redis_port)
    await redis_service.connect()
    pubsub = await redis_service.async_subscribe(realtime_agents_schema_channel)
    logger.info(f"Subscribed to channel '{realtime_agents_schema_channel}'")

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

    asyncio.create_task(redis_listener())


# Store active connections and their handlers
connections: Dict[
    WebSocket, list[OpenaiRealtimeAgentClient | OpenaiRealtimeTranscriptionClient]
] = {}


@app.websocket("/")
async def healthcheck_endpoint(
    websocket: WebSocket,
    model: str | None = None,
    connection_key: str | None = None,
    db_session: AsyncSession = Depends(get_db),
):
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

    strategy = ChatExecutor(
        client_websocket=websocket,
        realtime_agent_chat_data=realtime_agent_chat_data,
        instructions=instructions,
        redis_service=redis_service,
        python_code_executor_service=python_code_executor_service,
        tool_manager_service=tool_manager_service,
        connections=connections,
    )

    await strategy.execute()


@app.websocket("/ht")
async def healthcheck_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Message received: {data}")
    except WebSocketDisconnect:
        logger.info("Client disconnected")
