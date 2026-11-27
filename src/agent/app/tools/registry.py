"""
ToolRegistry: name-keyed store of callable tool specifications.

``AgentResolver`` populates the registry via ``register`` during resource
resolution; ``AgentLoop`` reads the specs via ``tool_specs`` (passed to
``LLMClient.chat``) and dispatches tool calls via ``execute``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field

from shared.models.agent_service import ToolResult


class ToolSpec(BaseModel):
    """Immutable descriptor for a single callable tool.

    ``parameters_schema`` follows JSON Schema draft-7 (OpenAI tool-call
    format) and is passed verbatim to the LLM so it can produce valid
    ``arguments`` JSON.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    parameters_schema: dict = Field(default_factory=dict)


class ToolRegistry:
    """Maps tool names to specs and async executor callables.

    ``AgentResolver`` calls ``register`` to add each tool resolved from the
    request pool.  ``AgentLoop`` calls ``tool_specs`` to get the list
    forwarded to the LLM and ``execute`` to run a named tool after the LLM
    requests it.

    Unknown names raise ``KeyError``, unless ``unknown_tool_executor`` is given:
    it then receives ``(name, args)`` for every unregistered name and may itself
    raise ``KeyError`` for names it does not handle. It is never advertised via
    ``tool_specs``.
    """

    def __init__(
        self,
        unknown_tool_executor: Callable[[str, dict], Awaitable[ToolResult]] | None = None,
    ) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._executors: dict[str, Callable[[dict], Awaitable[ToolResult]]] = {}
        self._unknown_tool_executor = unknown_tool_executor

    def register(
        self,
        spec: ToolSpec,
        executor: Callable[[dict], Awaitable[ToolResult]],
    ) -> None:
        """Register a tool spec and its async executor callable.

        Replaces any existing registration under the same name.
        """
        self._specs[spec.name] = spec
        self._executors[spec.name] = executor

    def tool_specs(self) -> list[ToolSpec]:
        """Return all registered ``ToolSpec`` objects for passing to ``LLMClient.chat``."""
        return list(self._specs.values())

    async def execute(self, name: str, args: dict) -> ToolResult:
        """Dispatch a tool call by name and return its result.

        Args:
            name: a registered ``ToolSpec.name``, or any name when an
                ``unknown_tool_executor`` handles it.
            args: parsed JSON arguments from the LLM tool-call request.

        Raises:
            KeyError: if ``name`` is unregistered and no ``unknown_tool_executor`` handles it.
        """
        executor = self._executors.get(name)

        if executor is None:
            if self._unknown_tool_executor is None:
                raise KeyError(name)

            return await self._unknown_tool_executor(name, args)

        return await executor(args)
