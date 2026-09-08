import pytest
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404

from utils.exception_handler import custom_exception_handler


@pytest.fixture(params=[True, False], ids=["debug_on", "debug_off"])
def any_debug(request, monkeypatch):
    """Run the test under both `DEBUG` values, since the handler branches on it."""
    monkeypatch.setattr("utils.exception_handler.DEBUG", request.param)
    return request.param


def test_http404_renders_as_404(any_debug):
    response = custom_exception_handler(
        Http404("No Graph matches the given query."), {}
    )

    assert response.status_code == 404
    assert response.data["status_code"] == 404
    assert response.data["code"] == "not_found"
    assert response.data["message"] == "NotFound: No Graph matches the given query."


def test_bare_http404_falls_back_to_default_detail(any_debug):
    response = custom_exception_handler(Http404(), {})

    assert response.status_code == 404
    assert response.data["message"] == "NotFound: Not found."


def test_django_permission_denied_renders_as_403(any_debug):
    response = custom_exception_handler(DjangoPermissionDenied("Nope."), {})

    assert response.status_code == 403
    assert response.data["status_code"] == 403
    assert response.data["message"] == "PermissionDenied: Nope."


def test_unknown_exception_still_renders_as_500(monkeypatch):
    monkeypatch.setattr("utils.exception_handler.DEBUG", False)

    response = custom_exception_handler(RuntimeError("boom"), {})

    assert response.status_code == 500
    assert b"RuntimeError: Unpredictable error" in response.content
