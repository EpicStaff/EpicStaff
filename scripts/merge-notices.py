#!/usr/bin/env python3
"""
Merges scripts/python-notices-partial.md into THIRD-PARTY-NOTICES.md.

The frontend generator (frontend/scripts/generate-third-party-notices.mjs)
fully rewrites THIRD-PARTY-NOTICES.md every time it runs. This merge step
inserts (or replaces) a "## Backend (Python)" section into that file
without disturbing the frontend section, and updates the top-level license
summary table with combined frontend+backend totals.

Behaviour:
  - Reads THIRD-PARTY-NOTICES.md (must exist, produced by the frontend
    generator first).
  - Reads scripts/python-notices-partial.md (must exist, produced by
    scripts/generate-python-notices.py).
  - If `## Backend (Python)` already exists in THIRD-PARTY-NOTICES.md,
    the entire backend block (up to `## How to refresh this file` or
    EOF) is replaced. Otherwise the backend block is inserted directly
    before `## How to refresh this file`.
  - Updates the top-level "## License summary" totals by adding backend
    package counts to the existing frontend counts.
  - Updates / inserts a `## Backend (Python)` subsection inside
    `## How to refresh this file` with run instructions.

Usage (from repository root):
    python scripts/merge-notices.py

Idempotent — safe to re-run.
"""

from __future__ import annotations

import re
import sys
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTICES_FILE = REPO_ROOT / "THIRD-PARTY-NOTICES.md"
PARTIAL_FILE = REPO_ROOT / "scripts" / "python-notices-partial.md"

BACKEND_HEADER = "## Backend (Python)"
REFRESH_HEADER = "## How to refresh this file"
SUMMARY_HEADER = "## License summary"


def log(msg: str) -> None:
    print(f"[merge-notices] {msg}", file=sys.stderr)


def read(path: Path) -> str:
    if not path.exists():
        log(f"missing file: {path}")
        sys.exit(1)
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Section utilities
# ---------------------------------------------------------------------------

def find_section(text: str, header: str) -> tuple[int, int] | None:
    """Return (start, end) byte offsets of a `## header` section, where end is
    the offset of the next `## ` header or EOF. Returns None if not found."""
    pattern = re.compile(rf"^{re.escape(header)}\s*$", re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return None
    start = m.start()
    # find next top-level header (## but not ###)
    next_match = re.search(r"^## (?!#)", text[m.end():], re.MULTILINE)
    if next_match:
        end = m.end() + next_match.start()
    else:
        end = len(text)
    return start, end


def parse_summary_table(text: str) -> tuple[OrderedDict[str, int], str] | None:
    """Parse the `## License summary` markdown table.

    Returns (license -> count, raw_summary_block) or None if the table can't
    be located.
    """
    section = find_section(text, SUMMARY_HEADER)
    if not section:
        return None
    start, end = section
    block = text[start:end]
    counts: OrderedDict[str, int] = OrderedDict()
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        if cells[0].lower() == "license" or cells[0].startswith("**"):
            # Skip header row and the **Total** row
            continue
        try:
            counts[cells[0]] = int(cells[1])
        except ValueError:
            continue
    return counts, block


def parse_backend_license_counts(partial: str) -> OrderedDict[str, int]:
    """Pull the per-license counts out of the partial's `### Python license
    summary` table."""
    counts: OrderedDict[str, int] = OrderedDict()
    in_table = False
    for line in partial.splitlines():
        s = line.strip()
        if s.startswith("### Python license summary"):
            in_table = True
            continue
        if in_table:
            if s.startswith("###") or s.startswith("##"):
                break
            if not s.startswith("|") or "---" in s:
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) != 2:
                continue
            if cells[0].lower() == "license" or cells[0].startswith("**"):
                continue
            try:
                counts[cells[0]] = int(cells[1])
            except ValueError:
                continue
    return counts


def render_summary_section(combined: dict[str, int]) -> str:
    items = sorted(combined.items(), key=lambda kv: (-kv[1], kv[0]))
    total = sum(combined.values())
    out: list[str] = []
    out.append(SUMMARY_HEADER)
    out.append("")
    out.append("Combined totals for frontend (npm) production dependencies and backend (Python) main dependencies.")
    out.append("")
    out.append("| License | Packages |")
    out.append("|---|---|")
    for lic, cnt in items:
        out.append(f"| {lic} | {cnt} |")
    out.append(f"| **Total** | **{total}** |")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Merge steps
# ---------------------------------------------------------------------------

def replace_section(text: str, header: str, new_block: str) -> str:
    """Replace existing `## header` section (up to next ## or EOF) with
    new_block. If not found, append at EOF."""
    section = find_section(text, header)
    if section is None:
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        return text + sep + new_block.rstrip() + "\n"
    start, end = section
    return text[:start] + new_block.rstrip() + "\n\n" + text[end:]


def insert_backend_section(notices: str, backend_block: str) -> str:
    """Insert / replace the Backend (Python) section, placing it directly
    before `## How to refresh this file` (or at EOF if absent)."""
    section = find_section(notices, BACKEND_HEADER)
    if section is not None:
        start, end = section
        return notices[:start] + backend_block.rstrip() + "\n\n" + notices[end:]

    refresh = find_section(notices, REFRESH_HEADER)
    if refresh is not None:
        start, _ = refresh
        return notices[:start] + backend_block.rstrip() + "\n\n" + notices[start:]

    sep = "" if notices.endswith("\n\n") else ("\n" if notices.endswith("\n") else "\n\n")
    return notices + sep + backend_block.rstrip() + "\n"


def patch_refresh_instructions(notices: str) -> str:
    """Ensure `## How to refresh this file` contains a `### Backend (Python)`
    subsection with run instructions. Idempotent — replaces existing block."""
    refresh = find_section(notices, REFRESH_HEADER)
    if refresh is None:
        # Nothing to patch — frontend generator should have produced this.
        return notices
    start, end = refresh
    block = notices[start:end]

    backend_instructions = (
        "### Backend (Python)\n"
        "\n"
        "Whenever any backend service's `pyproject.toml` `main` dependency group changes "
        "(additions, version bumps, removals in any of `src/django_app`, `src/crew`, "
        "`src/manager`, `src/knowledge`, `src/realtime`, `src/sandbox`, `src/webhook`, "
        "`src/tool`, `src/voice_app`), regenerate the backend section of this file.\n"
        "\n"
        "From the repository root, in PowerShell:\n"
        "\n"
        "```powershell\n"
        "python scripts/generate-python-notices.py\n"
        "python scripts/merge-notices.py\n"
        "```\n"
        "\n"
        "Both scripts use only the Python standard library; `pip-licenses` is installed "
        "into a throwaway venv at `scripts/.tmp_notices_venv/` and the venv is removed "
        "afterwards. `poetry` must be available on `PATH` because the first script calls "
        "`poetry export --only main` per service.\n"
        "\n"
        "The first script writes `scripts/python-notices-partial.md`; the second stitches "
        "that fragment into `THIRD-PARTY-NOTICES.md` and refreshes the combined license "
        "summary table at the top of the file. Re-running is safe — the backend section "
        "is replaced in place rather than appended.\n"
    )

    sub_pattern = re.compile(r"^### Backend \(Python\)\s*$", re.MULTILINE)
    sub_match = sub_pattern.search(block)
    if sub_match:
        # Replace existing backend subsection up to next ### or end of block.
        sub_start = sub_match.start()
        rest = block[sub_match.end():]
        next_sub = re.search(r"^### ", rest, re.MULTILINE)
        if next_sub:
            sub_end = sub_match.end() + next_sub.start()
        else:
            sub_end = len(block)
        new_block = block[:sub_start] + backend_instructions.rstrip() + "\n\n" + block[sub_end:]
    else:
        # Append before the trailing `### Manual overrides applied` subsection
        # if present, otherwise at the end of the refresh section.
        manual = re.search(r"^### Manual overrides applied\s*$", block, re.MULTILINE)
        if manual:
            new_block = block[:manual.start()] + backend_instructions.rstrip() + "\n\n" + block[manual.start():]
        else:
            sep = "" if block.endswith("\n\n") else ("\n" if block.endswith("\n") else "\n\n")
            new_block = block + sep + backend_instructions

    return notices[:start] + new_block.rstrip() + "\n\n" + notices[end:]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    notices = read(NOTICES_FILE)
    partial = read(PARTIAL_FILE)

    # 1. Update the top-level license summary with combined totals.
    fe_summary = parse_summary_table(notices)
    backend_counts = parse_backend_license_counts(partial)
    if fe_summary is None:
        log("could not locate frontend License summary table; leaving it untouched")
    else:
        fe_counts, _ = fe_summary
        combined: dict[str, int] = dict(fe_counts)
        for lic, cnt in backend_counts.items():
            combined[lic] = combined.get(lic, 0) + cnt
        new_summary = render_summary_section(combined)
        notices = replace_section(notices, SUMMARY_HEADER, new_summary)
        log(f"updated license summary: {sum(combined.values())} total packages")

    # 2. Insert / replace the Backend (Python) section.
    notices = insert_backend_section(notices, partial)
    log("backend section merged")

    # 3. Patch `How to refresh this file` with backend run instructions.
    notices = patch_refresh_instructions(notices)
    log("refresh instructions patched")

    # Tidy: ensure single trailing newline.
    notices = notices.rstrip() + "\n"
    NOTICES_FILE.write_text(notices, encoding="utf-8")
    log(f"wrote {NOTICES_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
