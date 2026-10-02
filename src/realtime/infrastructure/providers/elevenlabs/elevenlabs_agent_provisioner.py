import asyncio
import hashlib
import json
from collections.abc import AsyncIterator

import httpx
from domain.models.realtime_tool import RealtimeTool
from loguru import logger
from utils.singleton_meta import SingletonMeta

from infrastructure.messaging.redis_service import RedisService

_EL_API_BASE = "https://api.elevenlabs.io/v1"
_DEFAULT_LLM = "gemini-2.5-flash"
_HTTP_TIMEOUT = 30.0
_CACHE_TTL = 3600  # 1 hour
_LISTING_PAGE_SIZE = 100
_TOOL_NAME_SEPARATOR = "__"
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


def remote_agent_name(org_id: int, rt_agent_definition_id: int) -> str:
    """Return the name of the remote ElevenLabs agent owned by one realtime configuration.

    Provisioning PATCHes the agent it finds by name with the session's prompt and
    tools, so two configurations sharing a name would overwrite each other. The
    organization and the configuration are both part of the name to rule that out.
    """
    return f"EpicStaff-org{org_id}-rtdef{rt_agent_definition_id}"


def _local_tool_name(rt_tool: RealtimeTool) -> str:
    return rt_tool.name.replace(" ", "_")


def remote_tool_name(agent_name: str, rt_tool: RealtimeTool) -> str:
    """Return the name of the remote ElevenLabs tool record owned by one remote agent.

    Tool records live account-wide and provisioning PATCHes the record it finds by
    name, so agents sharing a tool name would overwrite each other's tool schema.
    The agent name is part of the tool name to rule that out.
    """
    return f"{agent_name}{_TOOL_NAME_SEPARATOR}{_local_tool_name(rt_tool)}"


def local_tool_name(agent_name: str, reported_tool_name: str) -> str:
    """Return the session-local tool name for a tool name reported by ElevenLabs.

    The agent payload names each tool by its local name while the tool record it
    points at carries the agent-prefixed name; either may come back in a
    `client_tool_call`, so the prefix is stripped when present.
    """
    return reported_tool_name.removeprefix(f"{agent_name}{_TOOL_NAME_SEPARATOR}")


class ElevenLabsAgentProvisioner(metaclass=SingletonMeta):
    def __init__(self, redis_service: RedisService):
        self.redis_service = redis_service
        self._provision_locks: dict[str, asyncio.Lock] = {}

    async def _iterate_listing(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        resource: str,
        search: str,
    ) -> AsyncIterator[dict]:
        """Yield every item of a paginated convai listing (`agents` or `tools`), page by page.

        `search` only narrows the listing server-side; callers still match names exactly.

        Raises:
            RuntimeError: The listing repeated a cursor. Treating that as "not found"
                would make the caller create a duplicate.
        """
        params: dict[str, str | int] = {"search": search, "page_size": _LISTING_PAGE_SIZE}
        seen_cursors: set[str] = set()
        while True:
            resp = await client.get(
                f"{_EL_API_BASE}/convai/{resource}", headers=headers, params=params
            )
            resp.raise_for_status()
            page = resp.json()
            for item in page.get(resource, []):
                yield item
            next_cursor = page.get("next_cursor")
            if not page.get("has_more") or not next_cursor:
                return
            if next_cursor in seen_cursors:
                raise RuntimeError(
                    f"ElevenLabs {resource} listing repeated cursor {next_cursor!r}; pagination is not advancing"
                )
            seen_cursors.add(next_cursor)
            params = {**params, "cursor": next_cursor}

    async def _find_tool_id(
        self, client: httpx.AsyncClient, headers: dict[str, str], tool_name: str
    ) -> str | None:
        """Return the id of the remote tool record with exactly this name, across all pages."""
        async for tool in self._iterate_listing(client, headers, "tools", tool_name):
            if tool.get("tool_config", {}).get("name") == tool_name:
                return tool["id"]
        return None

    async def _get_or_create_tool(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        agent_name: str,
        rt_tool: RealtimeTool,
    ) -> str:
        headers = {"xi-api-key": api_key}
        search_name = remote_tool_name(agent_name, rt_tool)
        existing_tool_id = await self._find_tool_id(client, headers, search_name)

        payload = {
            "tool_config": {
                "type": "client",
                "name": search_name,
                "description": rt_tool.description or f"Executes {rt_tool.name}",
                "expects_response": True,
                "parameters": rt_tool.parameters.model_dump(exclude_none=True),
            }
        }

        if existing_tool_id:
            t_id = existing_tool_id
            logger.info(
                f"EL Provisioner: Found existing tool '{search_name}' with ID: {t_id}. Updating..."
            )
            update_resp = await client.patch(
                f"{_EL_API_BASE}/convai/tools/{t_id}", headers=headers, json=payload
            )
            update_resp.raise_for_status()
            return t_id
        else:
            logger.info(f"EL Provisioner: Tool '{search_name}' not found. Creating new...")
            create_resp = await client.post(
                f"{_EL_API_BASE}/convai/tools", headers=headers, json=payload
            )
            create_resp.raise_for_status()
            new_data = create_resp.json()
            return new_data["id"]

    def _cache_key(self, api_key: str, agent_name: str) -> str:
        """Return the cache key of one remote agent.

        The key identifies the remote agent, not its content: the agent is a single
        object that every provisioning overwrites, so a content-keyed entry could
        outlive the content the agent actually holds (edit, then revert within the TTL).
        """
        raw = json.dumps({"api_key": api_key, "agent_name": agent_name}, sort_keys=True)
        return f"el_agent:{hashlib.md5(raw.encode()).hexdigest()}"

    def _content_hash(
        self,
        agent_name: str,
        instructions: str,
        voice: str,
        rt_tools: list[RealtimeTool],
        llm_model: str,
        language: str | None = None,
    ) -> str:
        # Everything `_build_agent_payload` sends must be in the hash, descriptions included,
        # and so must the names of the tool records the agent points at: an agent cached
        # while pointing at differently named records must not be served.
        tools_repr = sorted(
            f"{remote_tool_name(agent_name, t)}:{t.name}:{t.description}:{t.parameters.model_dump_json()}"
            for t in rt_tools
        )
        tts_model = _TTS_MODEL_EN if not language or language == "en" else _TTS_MODEL_MULTILINGUAL
        raw = json.dumps(
            {
                "instructions": instructions,
                "voice": voice,
                "tools": tools_repr,
                "llm": llm_model,
                "tts_model": tts_model,
                "language": language,
            },
            sort_keys=True,
        )
        return hashlib.md5(raw.encode()).hexdigest()

    async def _find_agent_id(
        self, client: httpx.AsyncClient, headers: dict[str, str], agent_name: str
    ) -> str | None:
        """Return the id of the remote agent with exactly this name, across all pages."""
        async for agent in self._iterate_listing(client, headers, "agents", agent_name):
            if agent["name"] == agent_name:
                return agent["agent_id"]
        return None

    async def invalidate_cache(self, api_key: str, agent_name: str) -> None:
        cache_key = self._cache_key(api_key, agent_name)
        redis = self.redis_service.aioredis_client
        if redis:
            await redis.delete(cache_key)
            logger.info(f"EL Provisioner: cache invalidated for key={cache_key}")

    async def get_or_create_agent(
        self,
        api_key: str,
        agent_name: str,
        instructions: str,
        voice: str,
        rt_tools: list[RealtimeTool],
        llm_model: str,
        language: str | None = None,
    ) -> str:
        voice = voice or "21m00Tcm4TlvDq8ikWAM"  # default to Rachel if empty/None
        logger.info(
            f"EL Provisioner: get_or_create_agent | agent_name={agent_name!r} | voice_id={voice!r} | llm={llm_model!r} | language={language!r}"
        )
        cache_key = self._cache_key(api_key, agent_name)
        content_hash = self._content_hash(
            agent_name, instructions, voice, rt_tools, llm_model, language
        )

        cached_agent_id = await self._cached_agent_id(cache_key, content_hash)
        if cached_agent_id:
            return cached_agent_id

        # One provisioning per remote agent at a time (within this process): concurrent
        # misses would otherwise create duplicate agents, or leave the cache describing
        # older content than the agent actually holds.
        async with self._provision_locks.setdefault(cache_key, asyncio.Lock()):
            cached_agent_id = await self._cached_agent_id(cache_key, content_hash)
            if cached_agent_id:
                return cached_agent_id

            agent_id, in_sync = await self._provision_agent(
                api_key, agent_name, instructions, voice, rt_tools, llm_model, language
            )
            redis = self.redis_service.aioredis_client
            # Only an agent that holds this content may be cached under its hash.
            if redis and in_sync:
                entry = json.dumps({"agent_id": agent_id, "content_hash": content_hash})
                await redis.set(cache_key, entry, ex=_CACHE_TTL)
            return agent_id

    async def _cached_agent_id(self, cache_key: str, content_hash: str) -> str | None:
        redis = self.redis_service.aioredis_client
        if not redis:
            return None
        cached = await redis.get(cache_key)
        if not cached:
            return None
        entry = json.loads(cached)
        # A hash mismatch means the remote agent was last provisioned with other
        # content, so it must be re-provisioned rather than served.
        if entry["content_hash"] != content_hash:
            return None
        logger.info(f"EL Provisioner: cache hit → agent_id={entry['agent_id']}")
        return entry["agent_id"]

    async def _provision_agent(
        self,
        api_key: str,
        agent_name: str,
        instructions: str,
        voice: str,
        rt_tools: list[RealtimeTool],
        llm_model: str,
        language: str | None,
    ) -> tuple[str, bool]:
        """Create or update the remote agent.

        Returns:
            The agent id, and whether the remote agent now holds this content. It is
            False when updating an existing agent failed and it is served as-is.
        """
        in_sync = True
        headers = {"xi-api-key": api_key}

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            tool_ids = []
            for rt_tool in rt_tools:
                tid = await self._get_or_create_tool(client, api_key, agent_name, rt_tool)
                tool_ids.append(tid)

            existing_agent_id = await self._find_agent_id(client, headers, agent_name)
            agent_payload = self._build_agent_payload(
                agent_name, instructions, voice, rt_tools, tool_ids, llm_model, language
            )

            if existing_agent_id:
                agent_id = existing_agent_id
                logger.info(f"EL Provisioner: Found existing agent '{agent_name}'. Updating...")
                res = await client.patch(
                    f"{_EL_API_BASE}/convai/agents/{agent_id}",
                    headers=headers,
                    json=agent_payload,
                )
                if not res.is_success:
                    in_sync = False
                    logger.warning(
                        f"EL Provisioner: PATCH agent failed ({res.status_code}): {res.text} — using existing agent as-is"
                    )
            else:
                logger.info(f"EL Provisioner: Agent '{agent_name}' not found. Creating...")
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

        return agent_id, in_sync

    def _build_agent_payload(
        self,
        name: str,
        instructions: str,
        voice: str,
        rt_tools: list[RealtimeTool],
        tool_ids: list[str],
        llm_model: str,
        language: str | None = None,
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
                    # The local name, not the remote record name: it is what the
                    # session's executors are registered under.
                    "name": _local_tool_name(tool_meta),
                    "description": tool_meta.description or f"Executes {tool_meta.name}",
                    "expects_response": True,
                    "parameters": {
                        "type": "object",
                        "properties": params_data.get("properties", {}),
                        "required": params_data.get("required", []),
                    },
                }
            )

        default_voice_id = "21m00Tcm4TlvDq8ikWAM"  # Rachel
        voice_id = voice if voice and voice.lower() not in _OPENAI_VOICE_NAMES else default_voice_id

        tts_model = _TTS_MODEL_EN if not language or language == "en" else _TTS_MODEL_MULTILINGUAL

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
