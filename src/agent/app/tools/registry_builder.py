from __future__ import annotations

import re
from collections import defaultdict
from typing import Self

from shared.models.agent_service import CollectionSpec, SearchConfigEntry
from shared.models.knowledge import GraphRagSearchConfig
from shared.models.tools import McpToolData, PythonCodeToolData

from app.exceptions import AgentServiceError, DuplicateToolNameError
from app.knowledge.client import KnowledgeClient
from app.knowledge.events import KnowledgeEventSink
from app.knowledge.target import KnowledgeSearchTarget
from app.sandbox.client import SandboxClient
from app.tools.executors.knowledge_search import (
    GraphKnowledgeSearchExecutor,
    KnowledgeSearchExecutor,
)
from app.tools.executors.mcp_tool import McpToolExecutor
from app.tools.executors.python_code import PythonCodeToolExecutor
from app.tools.mcp.gateway import McpToolGateway
from app.tools.registry import ToolRegistry, ToolSpec
from app.tools.system_registry import SystemToolRegistry, get_system_registry

_INVALID_TOOL_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]")

_QUERY_ONLY_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Natural-language search query.",
        }
    },
    "required": ["query"],
}


def _graph_schema(methods: list[str], default_method: str) -> dict:
    return {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language search query.",
            },
            "search_method": {
                "type": "string",
                "enum": methods,
                "default": default_method,
                "description": (
                    "basic = broad synthesis across documents; "
                    "local = entity/relationship-focused"
                ),
            },
        },
        "required": ["query"],
    }


def sanitize_tool_name(name: str) -> str:
    """Coerce a tool name to the LLM function-name pattern ^[A-Za-z0-9_-]{1,64}$."""
    cleaned = _INVALID_TOOL_NAME_CHARS.sub("_", name).strip("_")[:64]
    return cleaned or "tool"


def _search_method(config: GraphRagSearchConfig) -> str:
    """Extract search_method discriminator value from a GraphRagSearchConfig."""
    return config.search_params.search_method


class ToolRegistryBuilder:
    """Fluent builder that assembles a ``ToolRegistry`` for one agent run.

    Tool names are sanitized to the LLM-valid pattern ``^[A-Za-z0-9_-]{1,64}$``
    before being registered or exposed to the model.  Names must be unique across
    system and user tools; duplicates (including two names that collide after
    sanitisation) raise ``DuplicateToolNameError``.

    Method signatures
    -----------------
    ``add_python_code_tool(data: PythonCodeToolData)``
        Name, description, and args_schema are taken from ``data`` directly.

    ``add_mcp_tool(data: McpToolData, *, name: str, description: str, args_schema: dict)``
        ``McpToolData`` carries only transport/auth config; name, description,
        and args_schema must be supplied by the caller (``AgentResolver``
        derives them from the tool pool entry metadata).

    ``add_knowledge_tools(collection: CollectionSpec)``
        Registers one naive tool per naive entry (suffix ``_naive``) and one
        graph tool per unique graph rag_id (suffix ``_graph``).  Graph entries
        with the same rag_id are merged into a single tool with a
        ``search_method`` enum parameter.  If a candidate name is already
        taken, ``_{rag_id}`` is appended to disambiguate.
    """

    def __init__(
        self,
        sandbox: SandboxClient,
        mcp_gateway: McpToolGateway | None = None,
        knowledge_client: KnowledgeClient | None = None,
        knowledge_sink: KnowledgeEventSink | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._mcp_gateway = mcp_gateway
        self._knowledge_client = knowledge_client
        self._knowledge_sink = knowledge_sink
        self._registry = ToolRegistry()
        self._names: set[str] = set()
        self._built = False

    def _check_built(self) -> None:
        if self._built:
            raise RuntimeError("ToolRegistryBuilder is single-use")

    def _add_name(self, name: str) -> None:
        if name in self._names:
            raise DuplicateToolNameError(f"Tool name '{name}' is already registered")
        self._names.add(name)

    def add_system_tools(self, registry: SystemToolRegistry | None = None) -> Self:
        self._check_built()
        source = registry if registry is not None else get_system_registry()

        for entry in source.entries():
            clean_name = sanitize_tool_name(entry.name)
            self._add_name(clean_name)
            spec = ToolSpec(
                name=clean_name,
                description=entry.description,
                parameters_schema=entry.parameters_schema,
            )
            self._registry.register(spec, entry.executor)

        return self

    def add_python_code_tool(self, data: PythonCodeToolData) -> Self:
        """Register a python-code tool. Name, description, and schema come from ``data``."""
        self._check_built()
        clean_name = sanitize_tool_name(data.name)
        self._add_name(clean_name)
        spec = ToolSpec(
            name=clean_name,
            description=data.description,
            parameters_schema=data.args_schema.model_dump(),
        )
        executor = PythonCodeToolExecutor(self._sandbox, data)
        self._registry.register(spec, executor)
        return self

    def add_mcp_tool(
        self,
        data: McpToolData,
        *,
        name: str,
        description: str,
        args_schema: dict,
    ) -> Self:
        """Register an MCP tool.

        ``McpToolData`` carries transport/auth config only; ``name``,
        ``description``, and ``args_schema`` must be supplied by the caller.
        """
        self._check_built()
        clean_name = sanitize_tool_name(name)
        self._add_name(clean_name)
        spec = ToolSpec(
            name=clean_name,
            description=description,
            parameters_schema=args_schema,
        )
        if self._mcp_gateway is None:
            raise AgentServiceError(
                "McpToolGateway is not configured — cannot register MCP tools"
            )

        executor = McpToolExecutor(self._mcp_gateway, data, name)
        self._registry.register(spec, executor)
        return self

    def add_knowledge_tools(self, collection: CollectionSpec) -> Self:
        """Register knowledge tools for ``collection``.

        Naive entries each become one tool (suffix ``_naive``).
        Graph entries are grouped by ``rag_id``; each group produces one tool
        (suffix ``_graph``) with a ``search_method`` enum param.

        Naming
        ------
        Base: ``search_{collection.name}`` sanitized, truncated so suffix fits
        within 64 chars total.  If the candidate name is taken, ``_{rag_id}``
        is appended.
        """
        self._check_built()

        if self._knowledge_client is None:
            raise AgentServiceError(
                "KnowledgeClient is not configured — cannot register knowledge tools"
            )

        naive_entries = [e for e in collection.search_configs if e.rag_type == "naive"]
        graph_groups = self._group_graph_entries(collection.search_configs)

        for entry in naive_entries:
            self._register_naive_tool(collection, entry)

        for rag_id, entries in graph_groups.items():
            self._register_graph_tool(collection, rag_id, entries)

        return self

    def _register_naive_tool(
        self,
        collection: CollectionSpec,
        entry: SearchConfigEntry,
    ) -> None:
        suffix = "_naive"
        candidate = self._make_candidate(collection.name, suffix, entry.rag_id)
        description = (
            f"Fast semantic chunk search over '{collection.name}'. "
            "Best for direct factual lookups; returns most relevant passages."
        )

        if collection.description:
            description = f"{description} {collection.description}"

        target = KnowledgeSearchTarget(
            collection_id=collection.collection_id,
            rag_id=entry.rag_id,
            rag_type=entry.rag_type,
            search_config=entry.search_config,
            embedder_api_key=entry.embedder.config.api_key,
        )
        spec = ToolSpec(
            name=candidate,
            description=description,
            parameters_schema=_QUERY_ONLY_SCHEMA,
        )
        executor = KnowledgeSearchExecutor(
            self._knowledge_client, target, self._knowledge_sink
        )  # type: ignore[arg-type]
        self._registry.register(spec, executor)

        if self._knowledge_sink is not None:
            self._knowledge_sink.register_knowledge_tool(candidate)

    def _register_graph_tool(
        self,
        collection: CollectionSpec,
        rag_id: int,
        entries: list[SearchConfigEntry],
    ) -> None:
        suffix = "_graph"
        candidate = self._make_candidate(collection.name, suffix, rag_id)

        targets: dict[str, KnowledgeSearchTarget] = {}

        for entry in entries:
            assert isinstance(entry.search_config, GraphRagSearchConfig)
            method = _search_method(entry.search_config)
            targets[method] = KnowledgeSearchTarget(
                collection_id=collection.collection_id,
                rag_id=entry.rag_id,
                rag_type=entry.rag_type,
                search_config=entry.search_config,
                embedder_api_key=entry.embedder.config.api_key,
            )

        methods = sorted(targets.keys())
        default_method = "basic" if "basic" in targets else methods[0]

        description = (
            f"Knowledge-graph search over '{collection.name}'. "
            "Slower than semantic search; choose search_method: "
            "'basic' for broad questions needing synthesis across many documents, "
            "'local' for questions about specific entities and their relationships."
        )

        if collection.description:
            description = f"{description} {collection.description}"

        schema = _graph_schema(methods, default_method)
        spec = ToolSpec(
            name=candidate, description=description, parameters_schema=schema
        )
        executor = GraphKnowledgeSearchExecutor(
            self._knowledge_client, targets, default_method, self._knowledge_sink
        )  # type: ignore[arg-type]
        self._registry.register(spec, executor)

        if self._knowledge_sink is not None:
            self._knowledge_sink.register_knowledge_tool(candidate)

    def _make_candidate(self, collection_name: str, suffix: str, rag_id: int) -> str:
        max_base_len = 64 - len(suffix)
        raw_base = sanitize_tool_name(f"search_{collection_name}")
        base = raw_base[:max_base_len].rstrip("_")
        candidate = base + suffix

        if candidate in self._names:
            candidate = f"{candidate}_{rag_id}"

        self._add_name(candidate)
        return candidate

    @staticmethod
    def _group_graph_entries(
        entries: list[SearchConfigEntry],
    ) -> dict[int, list[SearchConfigEntry]]:
        groups: dict[int, list[SearchConfigEntry]] = defaultdict(list)

        for entry in entries:
            if entry.rag_type == "graph":
                groups[entry.rag_id].append(entry)

        return dict(groups)

    def build(self) -> ToolRegistry:
        self._check_built()
        self._built = True
        return self._registry
