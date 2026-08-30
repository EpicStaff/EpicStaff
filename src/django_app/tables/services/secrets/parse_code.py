import ast

GET_SECRET_FUNC = "get_secret"


def parse_secret_names(*, code: str) -> set[str]:
    """The set of names this code asks for via get_secret("NAME")."""
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
