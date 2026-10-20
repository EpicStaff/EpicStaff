"""Reads the manager role's grants out of src/crewdb/custom-docker-entrypoint.sh.

The entrypoint grants table privileges in three places that must agree: the
grant_manager_permissions function (run at container start), the auto-grant event trigger
(run when a migration creates a table) and REQUIRED_TABLES (what start-up waits for).
"""

import re
from pathlib import Path

ENTRYPOINT = Path(__file__).resolve().parents[2] / "crewdb" / "custom-docker-entrypoint.sh"

_QUOTED_IDENTIFIER = re.compile(r"'([a-z_]+)'")
_GRANT_TARGET = re.compile(r"ON TABLE ([a-z_]+)")
_NOT_TABLES = {"public"}


def _text() -> str:
    return ENTRYPOINT.read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    text = _text()
    start = text.index(f"\n{name}() {{")
    return text[start : text.index("\n}\n", start)]


def grant_manager_sql(role: str) -> str:
    """Return the SQL grant_manager_permissions runs, for ``role``, as psql would receive it."""
    body = _function_body("grant_manager_permissions")
    heredoc = body[body.index("<<EOF\n") + len("<<EOF\n") : body.rindex("\nEOF")]
    return heredoc.replace("\\$", "$").replace("${manager_user}", role)


def tables_in_grant_function() -> set[str]:
    sql = grant_manager_sql("<manager role>")
    return (set(_QUOTED_IDENTIFIER.findall(sql)) | set(_GRANT_TARGET.findall(sql))) - _NOT_TABLES


def tables_in_auto_grant_trigger() -> set[str]:
    body = _function_body("install_event_triggers")
    manager_section = body[body.index("-- manager:") : body.index("-- knowledge:")]
    return set(_QUOTED_IDENTIFIER.findall(manager_section))


def required_tables() -> set[str]:
    text = _text()
    start = text.index("REQUIRED_TABLES=(")
    return set(re.findall(r'"([a-z_]+)"', text[start : text.index("\n)", start)]))
