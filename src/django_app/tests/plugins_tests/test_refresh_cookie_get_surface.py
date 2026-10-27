"""Only POST handlers read the refresh cookie, with one exception: the plugin authorize GET.

`Path=/` sends the refresh cookie with every request to EpicStaff's host, including a plugin
page's cross-site GETs that no CORS rule stops. A GET that authenticated from the cookie would
act for the person on such a request, so the plugin authorize endpoint, which only redirects to
fixed targets, is the single GET allowed to read it.
"""

import ast
from pathlib import Path

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

DJANGO_APP = Path(__file__).resolve().parents[2]
SKIPPED_DIRECTORIES = {"tests", "migrations", ".venv", "__pycache__", "node_modules"}
READER = "get_refresh_from_cookie"
ALLOWED_GET = ("PluginAuthorizeView", "get")


def _source_files():
    for path in DJANGO_APP.rglob("*.py"):
        if not SKIPPED_DIRECTORIES & set(path.relative_to(DJANGO_APP).parts):
            yield path


def _calls_reader(function: ast.AST) -> bool:
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            called = node.func
            name = called.id if isinstance(called, ast.Name) else getattr(called, "attr", None)
            if name == READER:
                return True
    return False


def _callers() -> set[tuple[str, str, str]]:
    """Every `(module, class, function)` that calls the reader; class is "" at module level."""
    callers = set()
    for path in _source_files():
        module = str(path.relative_to(DJANGO_APP))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=module)
        for node in tree.body:
            classes = [node] if isinstance(node, ast.ClassDef) else []
            functions = [node] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else []
            for function in functions:
                if function.name != READER and _calls_reader(function):
                    callers.add((module, "", function.name))
            for class_node in classes:
                for member in class_node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and _calls_reader(member):
                        callers.add((module, class_node.name, member.name))
    return callers


def test_every_reader_of_the_refresh_cookie_is_a_post_handler_except_plugin_authorize():
    callers = _callers()
    readers = {(class_name, function) for _, class_name, function in callers}

    assert ALLOWED_GET in readers
    assert {"CookieTokenRefreshView", "LogoutView"} <= {class_name for class_name, _ in readers}
    unexpected = sorted(caller for caller in callers if caller[2] != "post" and caller[1:] != ALLOWED_GET)
    assert unexpected == []


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["refresh", "logout", "profile_password_change_confirm"])
def test_the_cookie_endpoints_refuse_get(route, regular_user, jwt_tokens):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")

    response = client.get(reverse(route), HTTP_COOKIE=f"auth.refresh={jwt_tokens['refresh']}")

    assert response.status_code == 405
