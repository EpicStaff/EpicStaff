"""The plugin docs hold together: links and anchors resolve, the index lists every page, and
no page carries internal wording.

Adding a page: put it under `docs/plugins/<tutorial|how-to|reference|explanation|operator>/`
and link it from `docs/plugins/README.md`; these tests then check its links like every other.
"""

import os
import re
from pathlib import Path
from urllib.parse import unquote

import pytest

from conftest import REPO_ROOT

DOCS = REPO_ROOT / "docs" / "plugins"
README = DOCS / "README.md"
SAMPLE_README = REPO_ROOT / "plugin-samples" / "weather" / "README.md"
DOC_PAGES = sorted(DOCS.rglob("*.md"))
PAGES_WITH_LINKS = [*DOC_PAGES, SAMPLE_README]
LINKED_FROM_README = [
    *(page for page in DOC_PAGES if page != README),
    DOCS / "reference" / "manifest.schema.json",
]

# The published page set. A missing page fails here by name.
DOCUMENTED_PAGES = [
    "README.md",
    "tutorial/build-your-first-plugin.md",
    "how-to/call-epicstaff-from-the-backend.md",
    "how-to/database-migrations.md",
    "how-to/declare-access.md",
    "how-to/external-callbacks.md",
    "how-to/frontend-in-the-frame.md",
    "how-to/install-hook.md",
    "how-to/local-development.md",
    "how-to/org-removed-hook.md",
    "how-to/outbound-hosts.md",
    "how-to/public-paths.md",
    "how-to/settings.md",
    "how-to/sign-and-package.md",
    "how-to/upgrade-hook.md",
    "how-to/user-permissions.md",
    "reference/cli.md",
    "reference/compatibility-and-versioning.md",
    "reference/database.md",
    "reference/error-codes.md",
    "reference/frame-protocol.md",
    "reference/gateway-context.md",
    "reference/hook-api.md",
    "reference/js-sdk.md",
    "reference/limits.md",
    "reference/manifest.md",
    "reference/manifest.schema.json",
    "reference/python-sdk.md",
    "reference/runtime.md",
    "reference/service-account-api.md",
    "reference/token-exchange.md",
    "explanation/accepted-risks.md",
    "explanation/architecture.md",
    "explanation/lifecycle.md",
    "explanation/security-model.md",
    "explanation/trust-and-signing.md",
    "operator/enable-plugins.md",
]

INTERNAL_WORDING = {
    "a slice number": re.compile(r"\bslices?\s+\d", re.IGNORECASE),
    "a spike number": re.compile(r"\bspikes?\s+\d", re.IGNORECASE),
    "a prototype plugin": re.compile(r"\b(?:doc[ _-]?editor|chat[ _-]?admin)\b", re.IGNORECASE),
    # Design documents live outside this repository, in the team's configuration repository.
    "the internal design docs": re.compile(r"docs/proposals|epicstaff-claude-code", re.IGNORECASE),
}

FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
INLINE_CODE = re.compile(r"`[^`]*`")
# `[text](target)` and `![alt](target)`, with link text that may wrap onto the next line and
# hold one level of brackets, and an optional title after the target.
LINK = re.compile(
    r"\[(?:[^\[\]]|\[[^\[\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)"
)
MARKDOWN_LINK_TEXT = re.compile(r"\[([^\]]*)\]\([^)]*\)")
URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def lines_outside_code_blocks(page: Path) -> list[str]:
    lines, fence = [], None
    for line in page.read_text(encoding="utf-8").splitlines():
        if fence is None and (opening := FENCE.match(line)):
            fence = opening.group(1)[0] * 3
        elif fence is not None and line.strip().startswith(fence):
            fence = None
        elif fence is None:
            lines.append(line)
    return lines


def prose(page: Path) -> str:
    """The page without its fenced code blocks and inline code: what Markdown renders as links."""
    paragraphs = "\n".join(lines_outside_code_blocks(page)).split("\n\n")
    return "\n\n".join(INLINE_CODE.sub("", paragraph) for paragraph in paragraphs)


def heading_anchor(heading: str) -> str:
    """The id GitHub gives a heading: lower case, punctuation dropped, spaces as hyphens."""
    text = MARKDOWN_LINK_TEXT.sub(r"\1", heading).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors(page: Path) -> set[str]:
    found, seen = set(), {}
    for line in lines_outside_code_blocks(page):
        if heading := HEADING.match(line):
            anchor = heading_anchor(heading.group(1))
            repeats = seen.get(anchor, 0)
            seen[anchor] = repeats + 1
            found.add(anchor if repeats == 0 else f"{anchor}-{repeats}")
    return found


def relative_links(page: Path) -> list[str]:
    return [target for target in LINK.findall(prose(page)) if not URL_SCHEME.match(target)]


def link_destination(page: Path, target: str) -> tuple[Path, str]:
    path, _, fragment = target.partition("#")
    destination = Path(os.path.normpath(page.parent / unquote(path))) if path else page
    return destination, fragment


def exists_with_exact_case(path: Path) -> bool:
    # macOS finds `Manifest.md` for `manifest.md`; the Linux CI runner and GitHub do not.
    current = REPO_ROOT
    for part in path.relative_to(REPO_ROOT).parts:
        if not current.is_dir() or part not in os.listdir(current):
            return False
        current = current / part
    return True


def page_id(page: Path) -> str:
    return str(page.relative_to(REPO_ROOT))


@pytest.mark.parametrize("page", PAGES_WITH_LINKS, ids=page_id)
def test_every_relative_link_names_a_file_in_the_repository(page):
    broken = []
    for target in relative_links(page):
        destination, _ = link_destination(page, target)
        if not destination.is_relative_to(REPO_ROOT):
            broken.append(f"{target}: leaves the repository")
        elif not exists_with_exact_case(destination):
            broken.append(f"{target}: no such file or directory")

    assert broken == []


@pytest.mark.parametrize("page", PAGES_WITH_LINKS, ids=page_id)
def test_every_anchor_names_a_heading_of_its_page(page):
    broken = []
    for target in relative_links(page):
        destination, fragment = link_destination(page, target)
        if not fragment or not destination.is_file():
            continue
        if destination.suffix != ".md":
            broken.append(f"{target}: anchors work only into Markdown pages")
        elif fragment not in anchors(destination):
            broken.append(f"{target}: {page_id(destination)} has no heading #{fragment}")

    assert broken == []


def test_the_readme_links_every_page():
    linked = {link_destination(README, target)[0] for target in relative_links(README)}

    assert [page_id(page) for page in LINKED_FROM_README if page not in linked] == []


def test_every_documented_page_exists():
    assert [page for page in DOCUMENTED_PAGES if not (DOCS / page).is_file()] == []


@pytest.mark.parametrize("page", PAGES_WITH_LINKS, ids=page_id)
def test_no_page_uses_internal_wording(page):
    text = page.read_text(encoding="utf-8")

    found = [
        f"{what}: {match.group(0)!r}"
        for what, pattern in INTERNAL_WORDING.items()
        for match in pattern.finditer(text)
    ]

    assert found == []


def test_anchors_follow_githubs_rules():
    assert heading_anchor("`epicstaff_plugin.database`") == "epicstaff_plugindatabase"
    assert heading_anchor("Sign-in and EpicStaff's login cookie") == "sign-in-and-epicstaffs-login-cookie"
    assert heading_anchor("11. Change the schema in a new version") == "11-change-the-schema-in-a-new-version"
    assert heading_anchor("Preparing 0.7.1 — offline") == "preparing-071--offline"
    assert heading_anchor("[Limits](limits.md) in short") == "limits-in-short"


def test_links_in_code_are_not_links(tmp_path):
    page = tmp_path / "page.md"
    page.write_text(
        "See [the manifest](manifest.md#fields) and\n"
        "[a wrapped\nlink](runtime.md).\n\n"
        "`[not](a-link.md)`\n\n"
        "```\n[not](a-link-either.md)\n# not a heading\n```\n"
        "## A heading\n",
        encoding="utf-8",
    )

    assert relative_links(page) == ["manifest.md#fields", "runtime.md"]
    assert anchors(page) == {"a-heading"}
