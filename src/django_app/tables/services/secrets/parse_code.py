"""Reads which secrets a piece of user Python asks for, without running it."""

import ast

GET_SECRET_FUNC = "get_secret"


def parse_secret_names(*, code: str) -> set[str]:
    """The set of names this code asks for via get_secret("NAME").

    This is a *check*, not a declaration. The declaration is
    PythonCode.secrets — the allow-list chosen through `secret_ids` — and that is
    also what gets injected at run time. This function only says what the code
    tries to read, so the two compare as sets:
    ``undeclared = parsed - declared``. PythonCodeSerializer.validate() rejects a
    mismatch at save time and declaration_validator aborts the session for
    anything that got past it.

    A set rather than a sequence because every caller does that subtraction and
    nothing depends on where in the file a name appeared. Callers that *display*
    names sort them: set iteration order is arbitrary, so an unsorted message
    would vary between runs.

    An AST walk rather than a regex: the name appearing in a comment or in an
    unrelated string literal must not count.

    Only string literals are visible to a static parse. A dynamic name —
    get_secret(some_var) — is invisible here, which is harmless: injection comes
    from the declaration, so a computed name still resolves as long as it was
    declared. It just cannot be checked, so it reaches the sandbox unverified.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()

    names: set[str] = set()
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
            names.add(first.value)

    return names
