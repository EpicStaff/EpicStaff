import pytest

from tables.utils.mixins import SerializedEvent, SSEMixin


class _StreamOfSerializedEvents(SSEMixin):
    def __init__(self, events, **kwargs):
        super().__init__(**kwargs)
        self._events = events

    async def get_initial_data(self):
        for event in self._events:
            yield event

    async def get_live_updates(self, pubsub):
        return
        yield  # make this an async generator


async def _frames(events):
    stream = _StreamOfSerializedEvents(events)
    return [frame async for frame in stream._data_generator(stream.get_initial_data)]


@pytest.mark.asyncio
async def test_serialized_event_data_is_sent_without_being_encoded_again():
    raw_data = '{"uuid":"a","text":"Agent ✓"}'

    frames = await _frames([SerializedEvent(event="messages", data=raw_data)])

    assert frames == ["event: messages\n", f"data: {raw_data}\n\n"]


@pytest.mark.asyncio
async def test_each_line_of_serialized_data_gets_its_own_data_field():
    frames = await _frames([SerializedEvent(event="messages", data='{\n  "uuid": "a"\n}')])

    assert frames == ["event: messages\n", 'data: {\ndata:   "uuid": "a"\ndata: }\n\n']
