#!/usr/bin/env python3
"""
Generate src/.dev.env, src/debug.env, src/.env.example from src/env.yaml.

Usage (from repository root):
    python scripts/generate_env.py                   # regenerate all three
    python scripts/generate_env.py --env dev         # single target
    python scripts/generate_env.py --env debug       # single target
    python scripts/generate_env.py --check           # diff check; exits 1 on mismatch

Requires: PyYAML  (pip install pyyaml)
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent

ENV_TARGETS: dict[str, Path] = {
    "dev": REPO_ROOT / "src" / ".dev.env",
    "debug": REPO_ROOT / "src" / "debug.env",
    "example": REPO_ROOT / "src" / ".env.example",
}

_MISSING = object()

BANNER_LINE = (
    "# GENERATED FROM src/env.yaml - do not edit. "
    "Run: python scripts/generate_env.py"
)

# Column at which inline comments are aligned in example output (0-based from
# start of KEY=value string).
EXAMPLE_COMMENT_COLUMN = 41


def _resolve_envs(var_cfg: dict, section_envs: list[str] | None) -> list[str] | None:
    """Return explicit envs list for a var, or None meaning all envs."""
    if "envs" in var_cfg:
        return var_cfg["envs"]
    if section_envs is not None:
        return section_envs
    return None


def _resolve_value(var_cfg: dict, env: str) -> tuple[str, str | None]:
    """
    Return (value_string, inline_comment_or_None) for the given env.

    Per-env key can be:
      - a plain scalar  →  value override, no inline comment
      - a mapping {value: ..., comment: ...}  →  value + inline comment
    """
    env_override = var_cfg.get(env, _MISSING)
    if env_override is not _MISSING:
        if isinstance(env_override, dict) and "value" in env_override:
            return str(env_override["value"]), env_override.get("comment")
        if env_override is None:
            return "", None
        return str(env_override), None

    default = var_cfg.get("default", "")
    return str(default), None


def _resolve_above_comment(var_cfg: dict, env: str) -> str | None:
    """Return the above-var comment text for this env, or None."""
    env_comment_key = f"{env}_comment"
    if env_comment_key in var_cfg:
        return var_cfg[env_comment_key]
    return var_cfg.get("comment")


def _render_comment_lines(text: str) -> list[str]:
    """
    Turn a comment string (may contain literal backslash-n sequences or real
    newlines) into rendered output lines, each starting with '#'.
    """
    rendered: list[str] = []
    for part in text.replace("\\n", "\n").split("\n"):
        stripped = part.strip()
        if stripped.startswith("#"):
            rendered.append(stripped)
        elif stripped:
            rendered.append(f"# {stripped}")
        else:
            rendered.append("#")
    return rendered


def _format_kv(key: str, value: str, inline_comment: str | None, env: str) -> str:
    """Format a KEY=value line, optionally with aligned inline comment."""
    base = f"{key}={value}"
    if not inline_comment:
        return base
    if env == "example":
        pad = max(1, EXAMPLE_COMMENT_COLUMN - len(base))
        return f"{base}{' ' * pad}# {inline_comment}"
    return f"{base}  # {inline_comment}"


def generate(env: str, schema: dict) -> str:
    """Build the complete file content string for the given env id."""
    lines: list[str] = [BANNER_LINE]

    header_text: str | None = (schema.get("header") or {}).get(env)
    if header_text:
        lines.append("")
        for raw in header_text.rstrip("\n").split("\n"):
            stripped = raw.strip()
            if stripped.startswith("#"):
                lines.append(stripped)
            elif stripped:
                lines.append(f"# {stripped}")
            else:
                lines.append("#")

    for group in schema.get("groups", []):
        no_banner: bool = group.get("no_banner", False)
        group_name: str = group["name"]
        sections: list[dict] = group.get("sections", [])

        # Collect rendered section blocks for this group to decide whether to
        # emit the group banner at all.
        section_blocks: list[list[str]] = []

        for section in sections:
            section_envs: list[str] | None = section.get("envs")
            vars_dict: dict = section.get("vars") or {}

            block: list[str] = []

            for var_name, var_cfg in vars_dict.items():
                if var_cfg is None:
                    var_cfg = {}

                # Raw comment-only line (no KEY=value).
                if isinstance(var_cfg, dict) and "raw_line" in var_cfg:
                    raw_envs = var_cfg.get("envs", section_envs)
                    if raw_envs is None or env in raw_envs:
                        block.append(var_cfg["raw_line"])
                    continue

                effective_envs = _resolve_envs(var_cfg, section_envs)
                if effective_envs is not None and env not in effective_envs:
                    continue

                above = _resolve_above_comment(var_cfg, env)
                if above:
                    block.extend(_render_comment_lines(above))

                actual_key = var_cfg.get("key", var_name)
                value, inline_comment = _resolve_value(var_cfg, env)
                block.append(_format_kv(actual_key, value, inline_comment, env))

            if not block:
                continue

            # Prefix the block with a blank line + optional section comment.
            section_comment: str | None = section.get("comment")
            prefixed: list[str] = [""]
            if section_comment:
                prefixed.extend(_render_comment_lines(section_comment))
            prefixed.extend(block)
            section_blocks.append(prefixed)

        if not section_blocks:
            continue

        if not no_banner:
            lines.append("")
            # If the group name already contains its own banner decoration (e.g.
            # "==== SERVICES ====") render it as-is; otherwise wrap with "=====".
            if group_name.startswith("="):
                lines.append(f"# {group_name}")
            else:
                lines.append(f"# ===== {group_name} =====")

        for block in section_blocks:
            lines.extend(block)

        if not no_banner:
            lines.append("# ==================")

    # Strip trailing blank lines, end with single newline.
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"


def load_schema() -> dict:
    schema_path = REPO_ROOT / "src" / "env.yaml"
    with schema_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def write_env(env: str, schema: dict) -> None:
    content = generate(env, schema)
    target = ENV_TARGETS[env]
    target.write_text(content, encoding="utf-8", newline="\n")
    print(f"Written: {target}")


def check_env(env: str, schema: dict) -> bool:
    """Return True if on-disk content matches generated content."""
    content = generate(env, schema)
    target = ENV_TARGETS[env]
    if not target.exists():
        print(f"MISSING: {target}")
        return False
    on_disk = target.read_text(encoding="utf-8")
    if on_disk == content:
        print(f"OK:      {target}")
        return True
    diff = list(
        difflib.unified_diff(
            on_disk.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=str(target),
            tofile="<generated>",
        )
    )
    print(f"DIFF:    {target}")
    sys.stdout.writelines(diff)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env",
        choices=list(ENV_TARGETS),
        help="Generate a single env file (default: all).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare generated output to disk; exit 1 on mismatch.",
    )
    args = parser.parse_args()

    schema = load_schema()
    targets = [args.env] if args.env else list(ENV_TARGETS)

    if args.check:
        results = [check_env(env, schema) for env in targets]
        sys.exit(0 if all(results) else 1)
    else:
        for env in targets:
            write_env(env, schema)


if __name__ == "__main__":
    main()
