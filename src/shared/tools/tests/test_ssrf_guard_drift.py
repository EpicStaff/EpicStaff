"""Drift detection for the `_ssrf_guard` function duplicated across sandbox
tools.

Each sandbox `main.py` is uploaded as standalone source (see
`upload_tools.py`) and cannot import from the rest of the codebase or from
another tool, so `_ssrf_guard` is manually copy-pasted into every tool that
needs it instead of living in one shared module. That's a known maintenance
liability: nothing stops a future edit to one copy (e.g. adding a check, or
worse, silently dropping one) from drifting out of sync with the rest of the
catalog.

This test parses every known copy with `ast` and compares a normalized dump
of the `_ssrf_guard` function body -- normalized by blanking out string
literals, since two copies (`notification_tool`, and historically
`web_fetch_tool` itself) intentionally use tool-specific wording in their
error messages ("fetch" vs. "notify a webhook", dash-style, etc.). What must
NOT drift is the actual security logic: the allowed schemes, the resolution
step, and the full set of `ipaddress` properties checked. If someone edits
the control flow of one copy (adds/removes/reorders a check, changes the
scheme allowlist, swaps `or` for `and`, etc.) without updating the rest, this
test fails and names the offending file.
"""

import ast
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent

# Every sandbox tool that carries its own copy of `_ssrf_guard`.
SSRF_GUARD_COPIES = [
    "web_fetch_tool",
    "notification_tool",
    "crewai_scrape_website_tool",
    "crewai_scrape_element_from_website_tool",
    "crewai_jina_scraper_website_tool",
    "crewai_website_search_tool",
]


class _BlankStringConstants(ast.NodeTransformer):
    """Replace every string-literal constant with a placeholder so that
    tool-specific wording ("fetch" vs "notify", dash style, etc.) doesn't
    register as drift, while any change to the actual control flow,
    comparisons, or the set of ipaddress properties checked still does."""

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value="<STR>"), node)
        return node


def _normalized_ssrf_guard_dump(tool_dir_name: str) -> str:
    main_path = TOOLS_ROOT / tool_dir_name / "main.py"
    source = main_path.read_text()
    tree = ast.parse(source, filename=str(main_path))

    function_defs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_ssrf_guard"
    ]
    assert len(function_defs) == 1, (
        f"{tool_dir_name}/main.py must define exactly one `_ssrf_guard` "
        f"function, found {len(function_defs)}."
    )

    function_def = function_defs[0]
    body = function_def.body
    # Some copies (e.g. notification_tool) keep an explanatory docstring;
    # others (per this change) use a comment above `def` instead, which
    # `ast` never sees. Docstring presence/absence is documentation, not
    # security logic, so drop a leading docstring statement before comparing.
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]

    # Function name/args/returns are already identical by construction (same
    # `def _ssrf_guard(url: str):` signature); drop them from the dump too so
    # only the body's control flow is compared.
    normalized_body = [_BlankStringConstants().visit(stmt) for stmt in body]
    return "\n".join(ast.dump(stmt, annotate_fields=False) for stmt in normalized_body)


class TestSsrfGuardDrift:
    def test_all_known_copies_exist_and_parse(self):
        for tool_dir_name in SSRF_GUARD_COPIES:
            main_path = TOOLS_ROOT / tool_dir_name / "main.py"
            assert main_path.exists(), f"expected {main_path} to exist"

    def test_ssrf_guard_control_flow_identical_across_all_copies(self):
        dumps = {name: _normalized_ssrf_guard_dump(name) for name in SSRF_GUARD_COPIES}

        canonical_name = "web_fetch_tool"
        canonical_dump = dumps[canonical_name]

        drifted = {
            name: dump
            for name, dump in dumps.items()
            if name != canonical_name and dump != canonical_dump
        }

        assert not drifted, (
            "The following copies of `_ssrf_guard` have drifted (in control "
            f"flow, not just wording) from the canonical `{canonical_name}` "
            f"version: {sorted(drifted)}. Every copy must independently "
            "implement the same scheme allowlist, DNS resolution, and full "
            "set of ipaddress private/loopback/link-local/reserved/"
            "multicast/unspecified checks -- update the drifted copy to "
            "match, or update the canonical version and propagate the "
            "change to every copy listed in SSRF_GUARD_COPIES."
        )

    def test_new_scraper_tool_copies_are_byte_identical_to_canonical(self):
        """The 4 web-scraping catalog tools were freshly guarded and had no
        pre-existing wording to preserve, so -- unlike `notification_tool`,
        which predates this test and keeps its own wording -- their copies
        should be verbatim, byte-for-byte identical to `web_fetch_tool`'s
        `_ssrf_guard`, including error message text. This gives the tightest
        possible drift detection for the 4 files this change touched."""
        import inspect

        from conftest import load_tool_main

        canonical_source = inspect.getsource(
            load_tool_main("web_fetch_tool")._ssrf_guard
        )

        byte_identical_copies = [
            "crewai_scrape_website_tool",
            "crewai_scrape_element_from_website_tool",
            "crewai_website_search_tool",
            "crewai_jina_scraper_website_tool",
        ]
        for tool_dir_name in byte_identical_copies:
            module = load_tool_main(tool_dir_name)
            source = inspect.getsource(module._ssrf_guard)
            assert source == canonical_source, (
                f"{tool_dir_name}/main.py's `_ssrf_guard` is not byte-"
                f"identical to web_fetch_tool's."
            )

    def test_guarded_get_byte_identical_across_scraper_tools(self):
        """`_guarded_get` performs the redirect-walking GET that the 4
        scraping tools use instead of a bare `requests.get(...)` (which
        follows redirects unguarded by default). It's copied inline into
        each tool for the same standalone-source reason as `_ssrf_guard`,
        and — unlike `_ssrf_guard`, which predates some of these tools and
        keeps tool-specific wording in a couple of copies — all 4 copies of
        `_guarded_get` were introduced together with no legacy wording to
        preserve, so they must be verbatim, byte-for-byte identical."""
        import inspect

        from conftest import load_tool_main

        byte_identical_copies = [
            "crewai_scrape_website_tool",
            "crewai_scrape_element_from_website_tool",
            "crewai_website_search_tool",
            "crewai_jina_scraper_website_tool",
        ]

        canonical_name = byte_identical_copies[0]
        canonical_source = inspect.getsource(
            load_tool_main(canonical_name)._guarded_get
        )

        for tool_dir_name in byte_identical_copies:
            module = load_tool_main(tool_dir_name)
            source = inspect.getsource(module._guarded_get)
            assert source == canonical_source, (
                f"{tool_dir_name}/main.py's `_guarded_get` is not byte-"
                f"identical to {canonical_name}'s."
            )
