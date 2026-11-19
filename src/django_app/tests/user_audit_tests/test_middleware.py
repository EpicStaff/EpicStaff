from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory

from user_audit.context import current_context
from user_audit.middleware import UserActionMiddleware


def test_middleware_opens_the_context_for_the_view_only():
    request = RequestFactory().get("/api/graphs/")
    seen_during_view = []

    def view(request_in_view):
        seen_during_view.append(current_context())
        return HttpResponse()

    UserActionMiddleware(view)(request)

    [context] = seen_during_view
    assert context.request is request
    assert current_context() is None


def test_middleware_is_installed():
    assert "user_audit.middleware.UserActionMiddleware" in settings.MIDDLEWARE
