"""
AgentResolver: resolves per-agent resource references into a live ToolRegistry
and an AgentContext, returning a ResolvedAgent ready for AgentLoop.run.

Collaborators
-------------
- ``AgentSpec``        — per-agent config + resource refs from the request.
- ``AgentRequest``     — top-level envelope carrying the resource pools.
- ``ToolRegistryBuilder`` — builds the ToolRegistry for this agent.
- ``AgentContext``     — mutable conversation state seeded from AgentSpec.
- ``SandboxClient``    — injected into ToolRegistryBuilder for python-code tools.
- ``KnowledgeClient``  — injected into ToolRegistryBuilder for knowledge search tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from app.exceptions import (
    AgentServiceError,
    UnknownCollectionRefError,
    UnknownS3RefError,
    UnknownToolRefError,
)
from app.knowledge.client import KnowledgeClient
from app.knowledge.events import KnowledgeEventSink
from app.loop.context import AgentContext
from app.resources.s3_manifest import build_s3_manifest
from app.sandbox.client import SandboxClient
from app.tools.mcp.gateway import McpToolGateway
from app.tools.registry import ToolRegistry
from app.tools.registry_builder import ToolRegistryBuilder
from shared.models.agent_service import (
    AgentRequest,
    AgentSpec,
    CollectionSpec,
    ContextAttachment,
    S3FileSpec,
)
from shared.models.tools import BaseToolData, McpToolData, PythonCodeToolData


@dataclass
class ResolvedAgent:
    """Holds everything needed to run one agent through ``AgentLoop``.

    Not a DTO — contains live objects (``ToolRegistry``) and must not be
    serialised.  ``attachments`` carries the informational S3 access manifest
    (and will carry RAG context once that pass is implemented).
    """

    agent_id: int
    context: AgentContext
    tools: ToolRegistry
    attachments: list[ContextAttachment] = field(default_factory=list)


class AgentResolver:
    """Resolves ``AgentSpec`` resource refs against the ``AgentRequest`` pools.

    Construction-time dependencies: ``SandboxClient``, ``McpToolGateway``,
    and ``KnowledgeClient`` (all passed to ``ToolRegistryBuilder``).

    Resolution steps
    ----------------
    1. Index the request pools by key (``unique_name`` for tools/collections,
       ``id`` for s3_files).
    2. For each ``agent.tool_refs``: look up in pool → raise
       ``UnknownToolRefError`` if missing → dispatch by unique_name prefix to
       the appropriate builder method.
    3. For each ``agent.collection_refs``: look up in collection pool → raise
       ``UnknownCollectionRefError`` if missing → register knowledge search tools.
    4. For each ``agent.s3_refs``: validate presence (raise on missing) and
       render them into a single informational ``ContextAttachment`` manifest.
    5. Build ``AgentContext`` from ``AgentSpec``, seeded with the attachments.
    6. Return ``ResolvedAgent``.
    """

    def __init__(
        self,
        sandbox: SandboxClient,
        mcp_gateway: McpToolGateway,
        knowledge_client: KnowledgeClient | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._mcp_gateway = mcp_gateway
        self._knowledge_client = knowledge_client

    async def resolve(
        self,
        agent: AgentSpec,
        request: AgentRequest,
        knowledge_sink: KnowledgeEventSink | None = None,
    ) -> ResolvedAgent:
        """Resolve all refs for ``agent`` against the pools in ``request``.

        ``knowledge_sink`` is per-request (typically the run's ``Emitter``)
        and must be passed as a parameter rather than stored on the resolver,
        which is built once at startup and shared across concurrent requests.
        """
        tool_pool: dict[str, BaseToolData] = {
            entry.unique_name: entry for entry in request.tools
        }
        collection_pool: dict[str, CollectionSpec] = {
            spec.unique_name: spec for spec in request.collections
        }
        s3_pool: dict[int, S3FileSpec] = {spec.id: spec for spec in request.s3_files}

        registry = await self._build_tool_registry(
            agent, tool_pool, collection_pool, knowledge_sink
        )
        names = [s.name for s in registry.tool_specs()]
        logger.debug("agent_id={} resolved {} tool(s): {}", agent.id, len(names), names)

        s3_specs = self._validate_s3_refs(agent, s3_pool)
        manifest = build_s3_manifest(s3_specs)
        attachments = [manifest] if manifest is not None else []

        if attachments:
            logger.info(
                "agent_id={} carrying s3 manifest for {} ref(s)",
                agent.id,
                len(s3_specs),
            )

        context = AgentContext(
            agent=agent,
            attachments=attachments,
            correlation_id=request.correlation_id,
        )

        return ResolvedAgent(
            agent_id=agent.id,
            context=context,
            tools=registry,
            attachments=attachments,
        )

    async def _build_tool_registry(
        self,
        agent: AgentSpec,
        tool_pool: dict[str, BaseToolData],
        collection_pool: dict[str, CollectionSpec],
        knowledge_sink: KnowledgeEventSink | None = None,
    ) -> ToolRegistry:
        builder = ToolRegistryBuilder(
            self._sandbox,
            self._mcp_gateway,
            self._knowledge_client,
            knowledge_sink,
        ).add_system_tools()

        for ref in agent.tool_refs:
            if ref not in tool_pool:
                raise UnknownToolRefError(
                    f"agent_id={agent.id}: tool_ref '{ref}' not found in request.tools pool"
                )

            entry = tool_pool[ref]
            prefix = ref.split(":")[0]

            if prefix == "python-code-tool":
                assert isinstance(entry.data, PythonCodeToolData)
                builder.add_python_code_tool(entry.data)

            elif prefix == "mcp-tool":
                assert isinstance(entry.data, McpToolData)
                desc = await self._mcp_gateway.describe(entry.data)
                builder.add_mcp_tool(
                    entry.data,
                    name=entry.data.tool_name,
                    description=desc.description,
                    args_schema=desc.input_schema,
                )

            else:
                raise AgentServiceError(
                    f"agent_id={agent.id}: tool prefix '{prefix}' (ref='{ref}') "
                    "is not supported in the agent service yet "
                    "(configured-tool and proxy-tool are crew-only)"
                )

        for ref in agent.collection_refs:
            if ref not in collection_pool:
                raise UnknownCollectionRefError(
                    f"agent_id={agent.id}: collection_ref '{ref}' not found in request.collections pool"
                )

            builder.add_knowledge_tools(collection_pool[ref])

        return builder.build()

    def _validate_s3_refs(
        self,
        agent: AgentSpec,
        s3_pool: dict[int, S3FileSpec],
    ) -> list[S3FileSpec]:
        specs: list[S3FileSpec] = []

        for file_id in agent.s3_refs:
            if file_id not in s3_pool:
                raise UnknownS3RefError(
                    f"agent_id={agent.id}: s3_ref id={file_id} not found in request.s3_files pool"
                )

            specs.append(s3_pool[file_id])

        return specs
