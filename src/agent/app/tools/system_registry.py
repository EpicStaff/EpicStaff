from __future__ import annotations

from typing import Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from shared.models.agent_service import ToolResult


class SystemToolEntry(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    description: str
    parameters_schema: dict
    executor: Callable[[dict], Awaitable[ToolResult]]


class SystemToolRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, SystemToolEntry] = {}

    def register(self, entry: SystemToolEntry) -> None:
        if entry.name in self._entries:
            raise ValueError(f"System tool '{entry.name}' is already registered")
        self._entries[entry.name] = entry

    def entries(self) -> list[SystemToolEntry]:
        return list(self._entries.values())

    def clear(self) -> None:
        self._entries.clear()


_system_registry = SystemToolRegistry()


def get_system_registry() -> SystemToolRegistry:
    return _system_registry


def system_tool(
    *,
    name: str,
    description: str,
    parameters_schema: dict,
    input_model: type[BaseModel] | None = None,
) -> Callable:
    def decorator(func: Callable) -> Callable:
        if input_model is not None:
            model = input_model

            async def executor(args: dict) -> ToolResult:
                try:
                    validated = model.model_validate(args)
                except Exception as exc:
                    return ToolResult(tool_call_id="", content=str(exc), is_error=True)

                result = await func(validated.model_dump())
                return ToolResult(tool_call_id="", content=str(result), is_error=False)

        else:

            async def executor(args: dict) -> ToolResult:
                result = await func(args)
                return ToolResult(tool_call_id="", content=str(result), is_error=False)

        entry = SystemToolEntry(
            name=name,
            description=description,
            parameters_schema=parameters_schema,
            executor=executor,
        )
        get_system_registry().register(entry)
        return func

    return decorator
