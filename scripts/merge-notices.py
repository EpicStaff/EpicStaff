#!/usr/bin/env python3
"""
Merges scripts/python-notices-partial.md into THIRD-PARTY-NOTICES.md.

The frontend generator (frontend/scripts/generate-third-party-notices.mjs)
fully rewrites THIRD-PARTY-NOTICES.md every time it runs. This merge step
inserts (or replaces) a "## Backend (Python)" section into that file
without disturbing the frontend section, and updates the top-level license
summary table with combined frontend+backend+embedded-assets totals.

The file has a known, fixed top-level structure that this script relies on
to locate section boundaries (rather than guessing from "the next `## `
header"), because several vendored license bodies embedded verbatim under
`## Notices` contain their own markdown-looking `## ` headers (e.g.
BlueOak-1.0.0's `## Purpose` / `## Acceptance` / ..., or a vendored
package's own `## <name> license` heading). The known order is:

    ## License summary
    ## Package index
    ## Notices
    ## Embedded assets (prebuilt epicchat-widget)
    ## Backend (Python)
    ## How to refresh this file

Each section a caller here cares about is located by anchoring on the exact
header text of the section that structurally follows it (falling back to
EOF when that successor is absent), never by "next `## ` of any kind".

Behaviour:
  - Reads THIRD-PARTY-NOTICES.md (must exist, produced by the frontend
    generator first).
  - Reads scripts/python-notices-partial.md (must exist, produced by
    scripts/generate-python-notices.py).
  - If `## Backend (Python)` already exists in THIRD-PARTY-NOTICES.md,
    the entire backend block (up to `## How to refresh this file` or
    EOF) is replaced. Otherwise the backend block is inserted directly
    before `## How to refresh this file`.
  - Updates the top-level "## License summary" totals with combined
    frontend+backend+embedded-assets counts. This is genuinely idempotent:
    the frontend-only baseline is derived by subtracting whatever backend
    and embedded-assets counts are already represented in the file itself
    (its own current `## Backend (Python)` and `## Embedded assets`
    sections — not the partial files, since those may describe content
    that hasn't been merged in yet), then the new backend + embedded counts
    from the partials are added back on top. Running this script standalone
    (the normal case when only backend dependencies changed) no longer
    inflates the totals, and running it right after the frontend generator
    wiped the file back to a frontend-only state doesn't under-subtract
    either.
  - Updates / inserts a `## Backend (Python)` subsection inside
    `## How to refresh this file` with run instructions.

Usage (from repository root):
    python scripts/merge-notices.py

Idempotent — safe to re-run, including standalone (without the frontend
generator having just run).
"""

from __future__ import annotations

import re
import sys
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTICES_FILE = REPO_ROOT / "THIRD-PARTY-NOTICES.md"
PARTIAL_FILE = REPO_ROOT / "scripts" / "python-notices-partial.md"
EMBEDDED_PARTIAL_FILE = REPO_ROOT / "scripts" / "embedded-assets-notices.md"

SUMMARY_HEADER = "## License summary"
PACKAGE_INDEX_HEADER = "## Package index"
EMBEDDED_HEADER = "## Embedded assets (prebuilt epicchat-widget)"
BACKEND_HEADER = "## Backend (Python)"
REFRESH_HEADER = "## How to refresh this file"

BACKEND_SUMMARY_TABLE_MARKER = "### Python license summary"
EMBEDDED_SUMMARY_TABLE_MARKER = "### Embedded assets license summary"


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


def _header_pattern(header: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(header)}\s*$", re.MULTILINE)


def find_section(
    text: str, header: str, next_header: str | None = None
) -> tuple[int, int] | None:
    """Return (start, end) offsets of a `## header` section.

    `end` is anchored on the exact structural successor header
    (`next_header`), not on "the next `## ` of any kind" — several vendored
    license texts embedded under `## Notices` contain their own `## `-style
    headers (BlueOak-1.0.0's `## Purpose`, a package's own `## <name>
    license`, ...) that would otherwise be mistaken for a real section
    boundary. Falls back to EOF if `next_header` is None or not found.

    If `header` occurs more than once in the file, the occurrence that is
    followed (later in the document) by an occurrence of `next_header` is
    preferred — that is the structural one. If none of the occurrences is
    followed by `next_header`, the last occurrence is used through EOF.

    Returns None if `header` itself isn't found at all.
    """
    matches = list(_header_pattern(header).finditer(text))
    if not matches:
        return None
    if next_header is None:
        return matches[0].start(), len(text)
    next_pattern = _header_pattern(next_header)
    for m in matches:
        next_match = next_pattern.search(text, m.end())
        if next_match:
            return m.start(), next_match.start()
    return matches[-1].start(), len(text)


def extract_table_counts(block: str) -> OrderedDict[str, int]:
    """Parse `| License | Packages |` markdown rows out of `block` into an
    ordered license -> count mapping, skipping the header row, separator
    row, and the `**Total**` row."""
    counts: OrderedDict[str, int] = OrderedDict()
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 2:
            continue
        if cells[0].lower() == "license" or cells[0].startswith("**"):
            continue
        try:
            counts[cells[0]] = int(cells[1])
        except ValueError:
            continue
    return counts


def isolate_subsection(text: str, marker: str) -> str | None:
    """Return the block of `text` starting right after a line beginning
    with `marker` (e.g. "### Python license summary") up to the next
    `##`/`###` header or EOF. Returns None if `marker` isn't found."""
    lines = text.splitlines()
    start_index = None
    for index, line in enumerate(lines):
        if line.strip().startswith(marker):
            start_index = index + 1
            break
    if start_index is None:
        return None
    block_lines: list[str] = []
    for line in lines[start_index:]:
        if line.strip().startswith("##"):
            break
        block_lines.append(line)
    return "\n".join(block_lines)


def parse_summary_table(text: str) -> tuple[OrderedDict[str, int], str] | None:
    """Parse the top-level `## License summary` markdown table.

    Returns (license -> count, raw_summary_block) or None if the table
    can't be located.
    """
    section = find_section(text, SUMMARY_HEADER, PACKAGE_INDEX_HEADER)
    if not section:
        return None
    start, end = section
    block = text[start:end]
    return extract_table_counts(block), block


def parse_named_table_counts(text: str, table_marker: str) -> OrderedDict[str, int]:
    """Pull the per-license counts out of a `### <table_marker>` summary
    table embedded anywhere in `text` (a partial fragment or a section
    slice of the main notices file)."""
    block = isolate_subsection(text, table_marker)
    if block is None:
        return OrderedDict()
    return extract_table_counts(block)


def render_summary_section(combined: dict[str, int]) -> str:
    items = sorted(combined.items(), key=lambda kv: (-kv[1], kv[0]))
    total = sum(combined.values())
    out: list[str] = []
    out.append(SUMMARY_HEADER)
    out.append("")
    out.append(
        "Combined totals for frontend (npm) production dependencies, assets embedded in the prebuilt epicchat-widget bundle, and backend (Python) main dependencies."
    )
    out.append("")
    out.append("| License | Packages |")
    out.append("|---|---|")
    for lic, cnt in items:
        out.append(f"| {lic} | {cnt} |")
    out.append(f"| **Total** | **{total}** |")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# License-summary idempotency
# ---------------------------------------------------------------------------


class NegativeLicenseCountError(Exception):
    """Raised when subtracting already-represented backend/embedded counts
    from the file's current combined summary would drive a license's count
    below zero — a sign the file's assumed structure doesn't hold."""


def compute_frontend_only_baseline(
    combined_counts: OrderedDict[str, int],
    already_represented_counts: list[OrderedDict[str, int]],
) -> dict[str, int]:
    """Subtract counts already baked into `combined_counts` by previously
    merged sections (the file's own backend section, embedded assets) to
    recover the frontend-only baseline, so re-adding fresh counts for those
    sections doesn't double-count them on a standalone re-run.

    Raises NegativeLicenseCountError if any license's count would go
    negative — writing a wrong table is worse than failing loudly. License
    keys that reach exactly zero are dropped.
    """
    baseline = dict(combined_counts)
    for represented in already_represented_counts:
        for lic, cnt in represented.items():
            baseline[lic] = baseline.get(lic, 0) - cnt
            if baseline[lic] < 0:
                raise NegativeLicenseCountError(
                    f"license '{lic}' count would go negative "
                    f"({baseline[lic]}) after subtracting already-represented "
                    "counts from the combined License summary table; the "
                    "file's structure doesn't match what merge-notices.py "
                    "assumes, refusing to write a wrong table"
                )
    return {lic: cnt for lic, cnt in baseline.items() if cnt != 0}


# ---------------------------------------------------------------------------
# Merge steps
# ---------------------------------------------------------------------------


def replace_section(
    text: str, header: str, new_block: str, next_header: str | None = None
) -> str:
    """Replace existing `## header` section (up to `next_header` or EOF)
    with new_block. If not found, append at EOF."""
    section = find_section(text, header, next_header)
    if section is None:
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        return text + sep + new_block.rstrip() + "\n"
    start, end = section
    return text[:start] + new_block.rstrip() + "\n\n" + text[end:]


def insert_backend_section(notices: str, backend_block: str) -> str:
    """Insert / replace the Backend (Python) section, placing it directly
    before `## How to refresh this file` (or at EOF if absent)."""
    section = find_section(notices, BACKEND_HEADER, REFRESH_HEADER)
    if section is not None:
        start, end = section
        return notices[:start] + backend_block.rstrip() + "\n\n" + notices[end:]

    refresh = find_section(notices, REFRESH_HEADER)
    if refresh is not None:
        start, _ = refresh
        return notices[:start] + backend_block.rstrip() + "\n\n" + notices[start:]

    sep = (
        "" if notices.endswith("\n\n") else ("\n" if notices.endswith("\n") else "\n\n")
    )
    return notices + sep + backend_block.rstrip() + "\n"


def insert_embedded_section(notices: str, embedded_block: str) -> str:
    """Insert / replace the Embedded assets section, placing it directly
    before `## Backend (Python)` (falling back to `## How to refresh this
    file`, then EOF)."""
    section = find_section(notices, EMBEDDED_HEADER, BACKEND_HEADER)
    if section is not None:
        start, end = section
        return notices[:start] + embedded_block.rstrip() + "\n\n" + notices[end:]

    for anchor in (BACKEND_HEADER, REFRESH_HEADER):
        anchor_section = find_section(notices, anchor)
        if anchor_section is not None:
            start, _ = anchor_section
            return notices[:start] + embedded_block.rstrip() + "\n\n" + notices[start:]

    sep = (
        "" if notices.endswith("\n\n") else ("\n" if notices.endswith("\n") else "\n\n")
    )
    return notices + sep + embedded_block.rstrip() + "\n"


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
        "`src/agent`, `src/manager`, `src/knowledge`, `src/realtime`, `src/sandbox`, "
        "`src/webhook`, `src/voice_app`), regenerate the backend section of this file.\n"
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
        rest = block[sub_match.end() :]
        next_sub = re.search(r"^### ", rest, re.MULTILINE)
        if next_sub:
            sub_end = sub_match.end() + next_sub.start()
        else:
            sub_end = len(block)
        new_block = (
            block[:sub_start] + backend_instructions.rstrip() + "\n\n" + block[sub_end:]
        )
    else:
        # Append before the trailing `### Manual overrides applied` subsection
        # if present, otherwise at the end of the refresh section.
        manual = re.search(r"^### Manual overrides applied\s*$", block, re.MULTILINE)
        if manual:
            new_block = (
                block[: manual.start()]
                + backend_instructions.rstrip()
                + "\n\n"
                + block[manual.start() :]
            )
        else:
            sep = (
                ""
                if block.endswith("\n\n")
                else ("\n" if block.endswith("\n") else "\n\n")
            )
            new_block = block + sep + backend_instructions

    return notices[:start] + new_block.rstrip() + "\n\n" + notices[end:]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    notices = read(NOTICES_FILE)
    partial = read(PARTIAL_FILE)
    embedded_partial = (
        EMBEDDED_PARTIAL_FILE.read_text(encoding="utf-8")
        if EMBEDDED_PARTIAL_FILE.exists()
        else None
    )
    if embedded_partial is None:
        log(
            f"embedded assets partial not found ({EMBEDDED_PARTIAL_FILE}); skipping that section"
        )

    # 1. Update the top-level license summary with combined totals.
    #
    # `notices` may already hold a *combined* summary from a previous merge
    # run (backend + embedded counts baked in), not a frontend-only one, so
    # first recover the frontend-only baseline by subtracting whatever the
    # file's own CURRENT Backend and Embedded assets sections already
    # represent, then add the fresh backend + embedded counts on top. Using
    # the file's own current sections (rather than the partials
    # unconditionally) matters because the frontend generator fully rewrites
    # THIRD-PARTY-NOTICES.md on every run, stripping both sections — in that
    # case nothing is "already represented" yet and nothing should be
    # subtracted, even though scripts/embedded-assets-notices.md still
    # exists unchanged on disk. This is what makes both a standalone re-run
    # (backend-only changed) and a post-frontend-regen run idempotent.
    current_summary = parse_summary_table(notices)
    backend_counts = parse_named_table_counts(partial, BACKEND_SUMMARY_TABLE_MARKER)
    embedded_counts = (
        parse_named_table_counts(embedded_partial, EMBEDDED_SUMMARY_TABLE_MARKER)
        if embedded_partial
        else OrderedDict()
    )
    existing_backend_section = find_section(notices, BACKEND_HEADER, REFRESH_HEADER)
    old_backend_counts = (
        parse_named_table_counts(
            notices[existing_backend_section[0] : existing_backend_section[1]],
            BACKEND_SUMMARY_TABLE_MARKER,
        )
        if existing_backend_section
        else OrderedDict()
    )
    existing_embedded_section = find_section(notices, EMBEDDED_HEADER, BACKEND_HEADER)
    old_embedded_counts = (
        parse_named_table_counts(
            notices[existing_embedded_section[0] : existing_embedded_section[1]],
            EMBEDDED_SUMMARY_TABLE_MARKER,
        )
        if existing_embedded_section
        else OrderedDict()
    )

    if current_summary is None:
        log("could not locate frontend License summary table; leaving it untouched")
    else:
        combined_counts, _ = current_summary
        try:
            baseline = compute_frontend_only_baseline(
                combined_counts, [old_backend_counts, old_embedded_counts]
            )
        except NegativeLicenseCountError as exc:
            log(f"refusing to update license summary: {exc}")
            return 1
        combined: dict[str, int] = dict(baseline)
        for counts in (backend_counts, embedded_counts):
            for lic, cnt in counts.items():
                combined[lic] = combined.get(lic, 0) + cnt
        new_summary = render_summary_section(combined)
        notices = replace_section(
            notices, SUMMARY_HEADER, new_summary, PACKAGE_INDEX_HEADER
        )
        log(f"updated license summary: {sum(combined.values())} total packages")

    # 2. Insert / replace the Backend (Python) section.
    notices = insert_backend_section(notices, partial)
    log("backend section merged")

    # 2b. Insert / replace the Embedded assets section (before the backend one).
    if embedded_partial:
        notices = insert_embedded_section(notices, embedded_partial)
        log("embedded assets section merged")

    # 3. Patch `How to refresh this file` with backend run instructions.
    notices = patch_refresh_instructions(notices)
    log("refresh instructions patched")

    # Tidy: ensure single trailing newline.
    notices = notices.rstrip() + "\n"
    NOTICES_FILE.write_text(notices, encoding="utf-8", newline="\n")
    log(f"wrote {NOTICES_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
