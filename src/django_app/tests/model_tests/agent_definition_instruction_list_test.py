from importlib import import_module
from types import SimpleNamespace

import pytest

from agents.models import AgentDefinition

instruction_list_migration = import_module(
    "agents.migrations.0010_agentdefinition_instruction_list"
)

# tests/conftest.py has an autouse fixture that queries the database; without the
# marker it would read the dev database instead of the test one.
pytestmark = pytest.mark.django_db


def test_instructions_joins_non_blank_contents_in_list_order():
    agent_definition = AgentDefinition(
        name="compiled",
        instruction_list=[
            {"name": "B.md", "content": "second"},
            {"name": "Blank.md", "content": " \n "},
            {"name": "A.md", "content": "first"},
        ],
    )

    assert agent_definition.instructions == "second\n\nfirst"


def test_instructions_is_empty_for_empty_instruction_list():
    assert AgentDefinition(name="empty").instructions == ""


def test_migration_moves_legacy_instructions_into_single_named_instruction():
    agent_definition = SimpleNamespace(
        instructions="Be concise.",
        instruction_list=[],
        metadata={"instructions_format": "markdown", "color": "blue"},
    )

    instruction_list_migration.convert_to_instruction_list(agent_definition)

    assert agent_definition.instruction_list == [
        {"name": "Instruction_1.md", "content": "Be concise."}
    ]
    assert agent_definition.metadata == {"color": "blue"}


def test_migration_leaves_blank_legacy_instructions_as_empty_list():
    agent_definition = SimpleNamespace(instructions="   ", instruction_list=[], metadata={})

    instruction_list_migration.convert_to_instruction_list(agent_definition)

    assert agent_definition.instruction_list == []


def test_migration_reverse_compiles_instruction_list_like_the_model_property():
    instruction_list = [
        {"name": "A.md", "content": "one"},
        {"name": "Blank.md", "content": ""},
        {"name": "B.md", "content": "two"},
    ]

    compiled = instruction_list_migration.compile_instructions(instruction_list)

    assert compiled == AgentDefinition(name="x", instruction_list=instruction_list).instructions
    assert compiled == "one\n\ntwo"
