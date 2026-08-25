import hashlib
import json
from typing import List, Optional

import httpx
from loguru import logger
from domain.models.realtime_tool import RealtimeTool
from infrastructure.messaging.redis_service import RedisService
from utils.singleton_meta import SingletonMeta

_EL_API_BASE = "https://api.elevenlabs.io/v1"
_DEFAULT_LLM = "gemini-2.5-flash"
_HTTP_TIMEOUT = 30.0
_CACHE_TTL = 3600  # 1 hour
_TTS_MODEL_EN = "eleven_turbo_v2"
_TTS_MODEL_MULTILINGUAL = "eleven_flash_v2_5"
_OPENAI_VOICE_NAMES = {
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "onyx",
    "nova",
    "sage",
    "shimmer",
    "verse",
}


class ElevenLabsAgentProvisioner(metaclass=SingletonMeta):
    def __init__(self, redis_service: RedisService):
        self.redis_service = redis_service

    async def _get_or_create_tool(
        self, client: httpx.AsyncClient, api_key: str, rt_tool: RealtimeTool
    ) -> str:
        headers = {"xi-api-key": api_key}
        search_name = rt_tool.name.replace(" ", "_")

        resp = await client.get(f"{_EL_API_BASE}/convai/tools", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        existing_tools = data.get("tools", [])

        existing_tool = next(
            (
                t
                for t in existing_tools
                if t.get("tool_config", {}).get("name") == search_name
            ),
            None,
        )

        payload = {
            "tool_config": {
                "type": "client",
                "name": search_name,
                "description": rt_tool.description or f"Executes {rt_tool.name}",
                "expects_response": True,
                "parameters": rt_tool.parameters.model_dump(exclude_none=True),
            }
        }

        if existing_tool:
            t_id = existing_tool["id"]
            logger.info(
                f"EL Provisioner: Found existing tool '{search_name}' with ID: {t_id}. Updating..."
            )
            update_resp = await client.patch(
                f"{_EL_API_BASE}/convai/tools/{t_id}", headers=headers, json=payload
            )
            update_resp.raise_for_status()
            return t_id
        else:
            logger.info(
                f"EL Provisioner: Tool '{search_name}' not found. Creating new..."
            )
            create_resp = await client.post(
                f"{_EL_API_BASE}/convai/tools", headers=headers, json=payload
            )
            create_resp.raise_for_status()
            new_data = create_resp.json()
            return new_data["id"]

    def _cache_key(
        self,
        api_key: str,
        instructions: str,
        voice: str,
        rt_tools: List[RealtimeTool],
        llm_model: str,
        language: Optional[str] = None,
    ) -> str:
        tools_repr = sorted(
            f"{t.name}:{t.parameters.model_dump_json()}" for t in rt_tools
        )
        tts_model = (
            _TTS_MODEL_EN
            if not language or language == "en"
            else _TTS_MODEL_MULTILINGUAL
        )
        raw = json.dumps(
            {
                "api_key": api_key,
                "instructions": instructions,
                "voice": voice,
                "tools": tools_repr,
                "llm": llm_model,
                "tts_model": tts_model,
                "language": language,
            },
            sort_keys=True,
        )
        return f"el_agent:{hashlib.md5(raw.encode()).hexdigest()}"

    async def invalidate_cache(
        self,
        api_key: str,
        instructions: str,
        voice: str,
        rt_tools: List[RealtimeTool],
        llm_model: str,
        language: Optional[str] = None,
    ) -> None:
        cache_key = self._cache_key(
            api_key, instructions, voice, rt_tools, llm_model, language
        )
        redis = self.redis_service.aioredis_client
        if redis:
            await redis.delete(cache_key)
            logger.info(f"EL Provisioner: cache invalidated for key={cache_key}")

    async def get_or_create_agent(
        self,
        api_key: str,
        instructions: str,
        voice: str,
        rt_tools: List[RealtimeTool],
        llm_model: str,
        language: Optional[str] = None,
    ) -> str:
        voice = voice or "21m00Tcm4TlvDq8ikWAM"  # default to Rachel if empty/None
        logger.info(
            f"EL Provisioner: get_or_create_agent | voice_id={voice!r} | llm={llm_model!r} | language={language!r}"
        )
        cache_key = self._cache_key(
            api_key, instructions, voice, rt_tools, llm_model, language
        )
        redis = self.redis_service.aioredis_client
        if redis:
            cached = await redis.get(cache_key)
            if cached:
                logger.info(f"EL Provisioner: cache hit → agent_id={cached}")
                return cached

        agent_name = "CrewAI-Main-Assistant"
        headers = {"xi-api-key": api_key}

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            tool_ids = []
            for rt_tool in rt_tools:
                tid = await self._get_or_create_tool(client, api_key, rt_tool)
                tool_ids.append(tid)

            agents_resp = await client.get(
                f"{_EL_API_BASE}/convai/agents", headers=headers
            )
            agents_resp.raise_for_status()
            existing_agents = agents_resp.json().get("agents", [])

            agent = next((a for a in existing_agents if a["name"] == agent_name), None)
            agent_payload = self._build_agent_payload(
                agent_name, instructions, voice, rt_tools, tool_ids, llm_model, language
            )

            if agent:
                agent_id = agent["agent_id"]
                logger.info(
                    f"EL Provisioner: Found existing agent '{agent_name}'. Updating..."
                )
                res = await client.patch(
                    f"{_EL_API_BASE}/convai/agents/{agent_id}",
                    headers=headers,
                    json=agent_payload,
                )
                if not res.is_success:
                    logger.warning(
                        f"EL Provisioner: PATCH agent failed ({res.status_code}): {res.text} — using existing agent as-is"
                    )
            else:
                logger.info(
                    f"EL Provisioner: Agent '{agent_name}' not found. Creating..."
                )
                res = await client.post(
                    f"{_EL_API_BASE}/convai/agents/create",
                    headers=headers,
                    json=agent_payload,
                )
                if not res.is_success:
                    logger.error(
                        f"EL Provisioner: POST agent create failed ({res.status_code}): {res.text}"
                    )
                res.raise_for_status()
                agent_id = res.json()["agent_id"]

        if redis:
            await redis.set(cache_key, agent_id, ex=_CACHE_TTL)
        return agent_id

    def _build_agent_payload(
        self,
        name: str,
        instructions: str,
        voice: str,
        rt_tools: List[RealtimeTool],
        tool_ids: List[str],
        llm_model: str,
        language: Optional[str] = None,
    ) -> dict:
        """Build the agent payload for the ElevenLabs API."""
        tools_config = []
        for i, tid in enumerate(tool_ids):
            tool_meta = rt_tools[i]
            params_data = tool_meta.parameters.model_dump(exclude_none=True)

            tools_config.append(
                {
                    "type": "client",
                    "tool_id": tid,
                    "name": tool_meta.name.replace(" ", "_"),
                    "description": tool_meta.description
                    or f"Executes {tool_meta.name}",
                    "expects_response": True,
                    "parameters": {
                        "type": "object",
                        "properties": params_data.get("properties", {}),
                        "required": params_data.get("required", []),
                    },
                }
            )

        _DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel
        voice_id = (
            voice
            if voice and voice.lower() not in _OPENAI_VOICE_NAMES
            else _DEFAULT_VOICE_ID
        )

        tts_model = (
            _TTS_MODEL_EN
            if not language or language == "en"
            else _TTS_MODEL_MULTILINGUAL
        )

        return {
            "name": name,
            "conversation_config": {
                "agent": {
                    "prompt": {
                        "prompt": instructions,
                        "llm": llm_model,
                        "first_message": "Hello! I am your AI assistant. How can I help you today?",
                        "tools": tools_config,
                    },
                },
                "tts": {"voice_id": voice_id, "model_id": tts_model},
            },
        }
