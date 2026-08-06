"""Session-start enforcement of the secret allow-list.

Save-time validation in PythonCodeSerializer is convenient but bypassable: import,
copy services, management commands and direct DB writes all reach PythonCode
without it. This is the boundary that actually holds.

It lives here rather than in converter_service because
convert_python_code_to_pydantic receives only a PythonCode and could not name the
offending node without a new argument at seven call sites. Walking the graph gives
node names for free and reports every violation at once.
"""

from dataclasses import dataclass

from tables.services.secrets.parse_code import GET_SECRET_FUNC, parse_secret_names
from tables.services.secrets.exceptions import UndeclaredSecretError
from tables.services.secrets.python_code_sites import GRAPH_PYTHON_CODE_SITES


@dataclass(frozen=True)
class DeclarationViolation:
    """One node whose code reads a secret it did not declare."""

    node_name: str
    node_type: str | None
    undeclared: list[str]
    declared: list[str]

    def describe(self) -> str:
        calls = ", ".join(f'get_secret("{name}")' for name in self.undeclared)
        declared = ", ".join(self.declared) or "none"
        return (
            f'node "{self.node_name}" calls {calls}, which '
            f"{'are' if len(self.undeclared) > 1 else 'is'} not declared for that "
            f"node. Declared: {declared}."
        )


class SecretDeclarationValidator:
    """Finds nodes whose code reads secrets they did not declare."""

    def violations(self, *, graph_id: int) -> list[DeclarationViolation]:
        """Every node in this graph whose code reads a secret it did not declare.

        Only the graph-owned sites are walked. A PythonCodeTool is org-owned rather
        than graph-owned, so it is not reachable from a graph id — it is gated in
        the converter instead (see assert_tool_secrets_declared), which already
        receives exactly the tools the session will use.
        """
        violations: list[DeclarationViolation] = []
        for site in GRAPH_PYTHON_CODE_SITES:
            violations.extend(self._violations_for(site=site, graph_id=graph_id))
        return violations

    @staticmethod
    def _violations_for(*, site, graph_id: int) -> list[DeclarationViolation]:
        code_field = site.code_field
        # The SQL prefilter cannot replace the AST pass — get_secret inside a
        # comment or an unrelated string matches it but must not count. It only
        # avoids parsing rows that cannot possibly match.
        rows = site.model.objects.filter(
            graph_id=graph_id,
            **{f"{code_field}__code__contains": GET_SECRET_FUNC},
        ).prefetch_related(f"{code_field}__secrets")

        found: list[DeclarationViolation] = []
        for row in rows:
            python_code = getattr(row, code_field)
            declared = {secret.name for secret in python_code.secrets.all()}
            parsed = parse_secret_names(code=python_code.code)
            undeclared = parsed - declared
            if not undeclared:
                continue
            found.append(
                DeclarationViolation(
                    node_name=_node_name(row=row, site=site),
                    node_type=site.node_type,
                    undeclared=sorted(undeclared),
                    declared=sorted(declared),
                )
            )
        return found


def _node_name(*, row, site) -> str:
    """A human-usable identity for the offending row.

    ConditionalEdge has no name field, so it falls back to its own id — the
    session-abort message has to be actionable and "unknown node" is not.
    """
    if site.name_field is None:
        return f"Conditional edge #{row.pk}"
    return getattr(row, site.name_field) or f"{site.model.__name__} #{row.pk}"


def assert_tool_secrets_declared(
    *, tool_name: str, code: str, declared: set[str]
) -> None:
    """Gate a custom tool's code against its declaration, by name.

    A PythonCodeTool is org-owned rather than graph-owned, so the graph walk above
    cannot reach it. Rather than traverse graph -> crews -> agents/tasks -> tools
    (four join tables plus recursive subgraphs, where every missed path is a silent
    hole), the converter calls this: it already holds exactly the tools the session
    will use, and a tool has a name, so the error can identify it.

    Raised inside create_session_data, hence inside run_session's try block, so it
    inherits the same session-ERROR-and-publish-nothing handling.
    """
    parsed = parse_secret_names(code=code)
    undeclared = parsed - declared
    if not undeclared:
        return
    calls = ", ".join(f'get_secret("{name}")' for name in sorted(undeclared))
    raise UndeclaredSecretError(
        f'Session aborted: tool "{tool_name}" calls {calls}, which '
        f"{'are' if len(undeclared) > 1 else 'is'} not declared for it. "
        f"Declared: {', '.join(sorted(declared)) or 'none'}."
    )


secret_declaration_validator = SecretDeclarationValidator()
