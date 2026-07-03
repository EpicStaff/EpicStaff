from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_personality: str | None = None
_instructions_template: Template | None = None
_rich_format: str | None = None


def _load_personality() -> str:
    global _personality
    if _personality is None:
        _personality = (_PROMPTS_DIR / "personality.md").read_text(encoding="utf-8")
    return _personality


def _load_instructions_template() -> Template:
    global _instructions_template
    if _instructions_template is None:
        text = (_PROMPTS_DIR / "instructions.md").read_text(encoding="utf-8")
        _instructions_template = Template(text)
    return _instructions_template


def _load_rich_format() -> str:
    global _rich_format
    if _rich_format is None:
        _rich_format = (_PROMPTS_DIR / "rich_format.md").read_text(encoding="utf-8")
    return _rich_format


@dataclass
class SystemPromptInputs:
    flow_name: str
    flow_description: str
    today_iso: str
    yesterday_iso: str
    tomorrow_iso: str
    node_summary: str
    nodes_section: str
    subflow_summary: str


def build_system_prompt(inputs: SystemPromptInputs) -> str:
    """Assemble the Flow Assistant persona system prompt from pre-computed inputs."""
    personality = _load_personality()
    instructions = _load_instructions_template().substitute(
        flow_name=inputs.flow_name,
        flow_description=inputs.flow_description,
        today_iso=inputs.today_iso,
        yesterday_iso=inputs.yesterday_iso,
        tomorrow_iso=inputs.tomorrow_iso,
        node_summary=inputs.node_summary,
        nodes_section=inputs.nodes_section,
        subflow_summary=inputs.subflow_summary,
    )
    return f"{personality}\n\n{instructions}\n\n{_load_rich_format()}"
