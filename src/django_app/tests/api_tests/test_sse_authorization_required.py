"""Every SSE stream must decide who may open it.

An SSE ticket proves only who the user is, so a stream without its own
`authorize()` would send its data to every ticket holder. `SSEMixin` has no
default: such a stream cannot even be instantiated.
"""

import json

import pytest
from asgiref.sync import async_to_sync
from django.test import RequestFactory
from rest_framework.exceptions import NotFound, PermissionDenied

import django_app.urls  # noqa: F401 -- imports every view module, registering every stream
from tables.utils.mixins import SSEMixin
from tables.views.flow_assistant_views import FlowAssistantStreamView
from tables.views.sse_views import RunSessionSSEView


def _all_subclasses(cls):
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _all_subclasses(subclass)


def _app_streams():
    # Test modules define their own streams, which never serve a request.
    return {
        stream
        for stream in _all_subclasses(SSEMixin)
        if not stream.__module__.startswith("tests.")
    }


def test_every_app_stream_authorizes_its_own_callers():
    app_streams = _app_streams()

    # Guards against a discovery that finds nothing and so passes vacuously.
    assert {RunSessionSSEView, FlowAssistantStreamView} <= app_streams
    without_authorize = sorted(
        f"{stream.__module__}.{stream.__qualname__}"
        for stream in app_streams
        if stream.authorize is SSEMixin.authorize
    )
    assert without_authorize == []


def test_a_stream_without_its_own_authorize_cannot_be_instantiated():
    class _StreamWithoutAuthorize(SSEMixin):
        async def get_initial_data(self):
            yield {"event": "secret", "data": "for the right users only"}

        async def get_live_updates(self, pubsub):
            return
            yield

    view = _StreamWithoutAuthorize.as_view()

    with pytest.raises(TypeError, match="authorize"):
        view(RequestFactory().get("/stream/", {"ticket": "any-ticket"}))


class _StreamRefusingEveryone(SSEMixin):
    refusal = PermissionDenied()

    async def authorize(self, request, *args, **kwargs):
        return self.refuse(self.refusal)

    async def get_initial_data(self):
        return
        yield

    async def get_live_updates(self, pubsub):
        return
        yield


@pytest.mark.parametrize(
    ("refusal", "expected_status", "expected_body"),
    [
        (
            NotFound("Conversation not found."),
            404,
            {"status_code": 404, "code": "not_found", "message": "Conversation not found."},
        ),
        (
            PermissionDenied(),
            403,
            {
                "status_code": 403,
                "code": "permission_denied",
                "message": "You do not have permission to perform this action.",
            },
        ),
    ],
    ids=["not_found", "permission_denied"],
)
def test_a_refused_stream_answers_with_the_api_error_body(refusal, expected_status, expected_body):
    view = _StreamRefusingEveryone()
    view.refusal = refusal

    response = async_to_sync(view.authorize)(request=None)

    assert response.status_code == expected_status
    assert json.loads(response.content) == expected_body


def test_a_missing_ticket_is_refused_before_authorize_runs():
    view = _StreamRefusingEveryone.as_view()

    response = async_to_sync(view)(RequestFactory().get("/stream/"))

    assert response.status_code == 401
    assert json.loads(response.content) == {
        "status_code": 401,
        "code": "invalid_sse_ticket",
        "message": "Invalid or expired SSE ticket.",
    }
