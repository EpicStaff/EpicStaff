"""Every SSE stream must decide who may open it.

An SSE ticket proves only who the user is, so a stream without its own
`authorize()` would send its data to every ticket holder. `SSEMixin` has no
default: such a stream cannot even be instantiated.
"""

import pytest
from django.test import RequestFactory

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


def test_a_stream_without_its_own_authorize_is_refused_before_it_reads_the_ticket():
    class _StreamWithoutAuthorize(SSEMixin):
        async def get_initial_data(self):
            yield {"event": "secret", "data": "for the right users only"}

        async def get_live_updates(self, pubsub):
            return
            yield

    view = _StreamWithoutAuthorize.as_view()

    with pytest.raises(TypeError, match="authorize"):
        view(RequestFactory().get("/stream/", {"ticket": "any-ticket"}))
