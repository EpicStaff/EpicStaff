from __future__ import annotations

from pathlib import Path

from utils.logger import logger

_SKILLS_DIR = Path(__file__).parent / "skills"

# Populated on first call; never invalidated (skills change only on deploy).
_skill_cache: dict[str, dict[str, str]] | None = None


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Extract key/value pairs from a --- ... --- YAML-style frontmatter block.

    Returns (frontmatter_dict, body_text).  If the block is absent or
    malformed, returns ({}, original_text).
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return {}, text

    meta: dict[str, str] = {}
    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        stripped = line.rstrip()
        if stripped == "---":
            closing_index = index
            break
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            meta[key.strip()] = value.strip()

    if closing_index is None:
        # No closing --- found — treat the whole file as body.
        return {}, text

    body = "".join(lines[closing_index + 1 :]).lstrip("\n")
    return meta, body


def _load_skills() -> dict[str, dict[str, str]]:
    cache: dict[str, dict[str, str]] = {}
    if not _SKILLS_DIR.is_dir():
        logger.warning(
            "flow_assistant_skills_loader: skills directory not found at {}",
            _SKILLS_DIR,
        )
        return cache

    for skill_dir in sorted(_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        slug = skill_dir.name
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            logger.warning(
                "flow_assistant_skills_loader: missing SKILL.md in {}",
                skill_dir,
            )
            continue
        try:
            raw = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "flow_assistant_skills_loader: could not read {}: {}",
                skill_file,
                exc,
            )
            continue

        meta, body = _parse_frontmatter(raw)
        description = meta.get("description", "")
        if not description:
            logger.warning(
                "flow_assistant_skills_loader: no description in frontmatter for skill '{}'",
                slug,
            )

        cache[slug] = {"name": slug, "description": description, "body": body}

    return cache


def _get_cache() -> dict[str, dict[str, str]]:
    global _skill_cache
    if _skill_cache is None:
        _skill_cache = _load_skills()
    return _skill_cache


def list_skills_summaries() -> list[dict]:
    """Return [{"slug": str, "description": str}, ...] for every vendored skill."""
    return [
        {"slug": slug, "description": entry["description"]}
        for slug, entry in _get_cache().items()
    ]


def load_skill_body(slug: str) -> str | None:
    """Return the body (post-frontmatter text) for slug, or None if unknown.

    Validates slug against the cached set — never joins user input into Path().
    """
    cache = _get_cache()
    entry = cache.get(slug)
    if entry is None:
        return None
    return entry["body"]
