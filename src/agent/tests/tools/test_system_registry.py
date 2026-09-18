"""
Tests for SystemToolRegistry and the @system_tool decorator.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from shared.models.agent_service import ToolResult
from app.tools.system_registry import (
    SystemToolRegistry,
    get_system_registry,
    system_tool,
)


@pytest.fixture(autouse=True)
def clear_registry():
    get_system_registry().clear()
    yield
    get_system_registry().clear()


async def test_decorator_registers_tool():
    @system_tool(
        name="greet",
        description="Greet someone.",
        parameters_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
    )
    async def greet(args: dict) -> str:
        return f"Hello, {args['name']}"

    entries = get_system_registry().entries()
    assert len(entries) == 1
    assert entries[0].name == "greet"
    assert entries[0].description == "Greet someone."


async def test_decorator_returns_original_function():
    @system_tool(
        name="identity",
        description="Returns input.",
        parameters_schema={},
    )
    async def identity(args: dict) -> dict:
        return args

    result = await identity({"x": 1})
    assert result == {"x": 1}


async def test_duplicate_name_raises_value_error():
    @system_tool(name="dup", description="First.", parameters_schema={})
    async def first(args: dict) -> str:
        return "first"

    with pytest.raises(ValueError, match="dup"):

        @system_tool(name="dup", description="Second.", parameters_schema={})
        async def second(args: dict) -> str:
            return "second"


async def test_executor_called_with_args_dict():
    @system_tool(
        name="echo",
        description="Echoes args.",
        parameters_schema={"type": "object", "properties": {"msg": {"type": "string"}}},
    )
    async def echo(args: dict) -> str:
        return args["msg"]

    entry = get_system_registry().entries()[0]
    result = await entry.executor({"msg": "hello"})

    assert isinstance(result, ToolResult)
    assert result.content == "hello"
    assert result.is_error is False


async def test_input_model_none_passes_dict_straight_through():
    @system_tool(
        name="raw",
        description="Raw dict.",
        parameters_schema={},
        input_model=None,
    )
    async def raw(args: dict) -> str:
        return str(args)

    entry = get_system_registry().entries()[0]
    result = await entry.executor({"key": "val"})

    assert result.is_error is False
    assert "key" in result.content


async def test_input_model_validates_and_rejects_bad_args():
    class Params(BaseModel):
        count: int

    @system_tool(
        name="counted",
        description="Needs an int.",
        parameters_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        },
        input_model=Params,
    )
    async def counted(args: dict) -> str:
        return str(args["count"])

    entry = get_system_registry().entries()[0]
    result = await entry.executor({"count": "not-an-int"})

    assert result.is_error is True


async def test_input_model_passes_valid_args():
    class Params(BaseModel):
        value: int

    @system_tool(
        name="valid_model",
        description="Needs an int.",
        parameters_schema={},
        input_model=Params,
    )
    async def valid_model_tool(args: dict) -> str:
        return str(args["value"])

    entry = get_system_registry().entries()[0]
    result = await entry.executor({"value": 42})

    assert result.is_error is False
    assert result.content == "42"


async def test_clear_empties_registry():
    @system_tool(name="temp", description="Temporary.", parameters_schema={})
    async def temp(args: dict) -> str:
        return ""

    assert len(get_system_registry().entries()) == 1
    get_system_registry().clear()
    assert len(get_system_registry().entries()) == 0


async def test_entries_returns_list_of_all_registered():
    @system_tool(name="tool_a", description="A.", parameters_schema={})
    async def tool_a(args: dict) -> str:
        return "a"

    @system_tool(name="tool_b", description="B.", parameters_schema={})
    async def tool_b(args: dict) -> str:
        return "b"

    names = {e.name for e in get_system_registry().entries()}
    assert names == {"tool_a", "tool_b"}
