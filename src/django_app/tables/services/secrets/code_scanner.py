import ast

GET_SECRET_FUNC = "get_secret"


def scan_secret_names(*, code: str) -> list[str]:
    """Names this code asks for via get_secret("NAME"), first-seen order, deduped.

    The declaration IS the source. Nothing else decides which credentials a node
    may read, so there is no client field to forward and no frontend involvement
    — which is what lets every Python context (nodes, conditional edges, decision
    table pre/post computation, custom tools) behave identically.

    An AST walk rather than a regex: the name appearing in a comment or in an
    unrelated string literal must not count as a declaration.

    Only string literals are visible to a static scan. A dynamic name —
    get_secret(some_var) — is not resolvable here and fails at call time inside
    the sandbox, which reports the names that WERE injected.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Unparseable code cannot execute either, so injecting nothing is
        # correct. Raising here would break session publishing over a node the
        # user has not finished writing.
        return []

    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        if isinstance(func, ast.Name):
            called = func.id  # from epicstaff_secrets import get_secret
        elif isinstance(func, ast.Attribute):
            called = func.attr  # epicstaff_secrets.get_secret(...)
        else:
            continue

        if called != GET_SECRET_FUNC or not node.args:
            continue

        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            if first.value not in names:
                names.append(first.value)

    return names
