from dataclasses import dataclass, field

from tables.models.python_models import linked_secrets_prefetch
from tables.services.secrets.exceptions import UndeclaredSecretError
from tables.services.secrets.parse_code import GET_SECRET_FUNC, parse_secret_names
from tables.services.secrets.python_code_sites import GRAPH_PYTHON_CODE_SITES


def binned_secret_names(python_code) -> set[str]:
    """Names the code links to that are in the recycle bin: still linked, but never read."""
    return {secret.name for secret in python_code.linked_secrets() if not secret.active}


def describe_unreadable_secrets(*, subject: str, owner: str, undeclared, binned, declared) -> str:
    """Why `subject` can't read some get_secret() names: not declared, or in the recycle bin.

    A name the code links to but whose secret is binned reads as declared in the editor,
    so it gets its own sentence instead of "not declared".
    """

    def calls(names: list[str]) -> str:
        return ", ".join(f'get_secret("{name}")' for name in names)

    in_bin = sorted(set(undeclared) & set(binned))
    missing = sorted(set(undeclared) - set(binned))
    sentences = []
    if missing:
        sentences.append(
            f"{subject} calls {calls(missing)}, which "
            f"{'are' if len(missing) > 1 else 'is'} not declared for {owner}. "
            f"Declared: {', '.join(sorted(declared)) or 'none'}."
        )
    if in_bin:
        sentences.append(
            f"{subject} calls {calls(in_bin)}, which "
            f"{'read secrets' if len(in_bin) > 1 else 'reads a secret'} in the recycle bin. "
            f"Restore it from the Recycle Bin, or pick another secret for {owner}."
        )
    return " ".join(sentences)


@dataclass(frozen=True)
class DeclarationViolation:
    """One node whose code reads a secret it did not declare, or one that's in the recycle bin."""

    node_name: str
    node_type: str | None
    undeclared: list[str]
    declared: list[str]
    binned: list[str] = field(default_factory=list)

    def describe(self) -> str:
        return describe_unreadable_secrets(
            subject=f'node "{self.node_name}"',
            owner="that node",
            undeclared=self.undeclared,
            binned=self.binned,
            declared=self.declared,
        )


class SecretDeclarationValidator:
    """Finds nodes whose code reads secrets they did not declare."""

    def violations(self, *, graph_id: int) -> list[DeclarationViolation]:
        """Every node in this graph whose code reads a secret it did not declare.

        Only the graph-owned sites are walked. A PythonCodeTool is org-owned rather
        than graph-owned, so it is not reachable from a graph id — it is gated in
        the converter instead.
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
        ).prefetch_related(f"{code_field}__secrets", linked_secrets_prefetch(code_field))

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
                    binned=sorted(binned_secret_names(python_code)),
                )
            )
        return found


def _node_name(*, row, site) -> str:
    """A human-usable identity for the offending row."""
    return getattr(row, site.name_field) or f"{site.model.__name__} #{row.pk}"


def assert_tool_secrets_declared(
    *, tool_name: str, code: str, declared: set[str], binned: set[str] = frozenset()
) -> None:
    """Gate a custom tool's code against its declaration, by name.

    `binned` are the names it links to whose secret is in the recycle bin: still refused,
    but named as binned.
    """
    parsed = parse_secret_names(code=code)
    undeclared = parsed - declared
    if not undeclared:
        return
    raise UndeclaredSecretError(
        describe_unreadable_secrets(
            subject=f'Session aborted: tool "{tool_name}"',
            owner="it",
            undeclared=undeclared,
            binned=binned,
            declared=declared,
        )
    )


secret_declaration_validator = SecretDeclarationValidator()
