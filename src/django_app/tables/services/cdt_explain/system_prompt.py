from functools import lru_cache
from pathlib import Path
from typing import Iterable

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_SECTION_ORDER = ("computation.md", "condition.md", "prompt.md", "manipulation.md")

_BLOCK_SECTIONS = {
    "pre_computation": "computation.md",
    "post_computation": "computation.md",
    "condition": "condition.md",
    "prompt": "prompt.md",
    "manipulation": "manipulation.md",
}

SUPPORTED_BLOCK_TYPES = frozenset(_BLOCK_SECTIONS)


@lru_cache(maxsize=None)
def _read(relative: str) -> str:
    return (_PROMPTS_DIR / relative).read_text(encoding="utf-8").strip()


@lru_cache(maxsize=None)
def _assemble(sections: tuple[str, ...]) -> str:
    parts = [_read("system.md")]
    parts.extend(_read(f"blocks/{name}") for name in sections)
    return "\n\n".join(parts)


def build_system_prompt(block_types: Iterable[str]) -> str:
    """Core prompt plus the sections covering `block_types`, deduplicated
    (pre and post computation share one section) and canonically ordered."""
    requested = set(block_types)
    unknown = requested - SUPPORTED_BLOCK_TYPES
    if unknown:
        raise ValueError(f"Unknown CDT block type(s): {', '.join(sorted(unknown))}")

    needed = {_BLOCK_SECTIONS[block_type] for block_type in requested}
    return _assemble(tuple(name for name in _SECTION_ORDER if name in needed))


def section_key(block_type: str) -> str:
    """The prompt section a block type loads. Blocks sharing a section share a
    byte-identical system prompt, which is what makes type-grouped batching cheap."""
    return _BLOCK_SECTIONS[block_type]


def clear_cache() -> None:
    """Drop the on-disk prompt cache. For tests and for editing prompts in dev
    without restarting the process."""
    _read.cache_clear()
    _assemble.cache_clear()
