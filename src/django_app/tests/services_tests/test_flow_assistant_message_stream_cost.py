"""Cost of forwarding the ``message`` field while the final JSON reply streams in.

The flow assistant receives its final answer as raw JSON tokens and forwards only
the growing ``message`` value to the client.  Each token must cost work
proportional to the token, not to everything received so far, or one long answer
burns CPU that grows with the square of its length inside the request's event loop.

Pure string handling — no database, no Redis.
"""

import json
import time

from tables.services.flow_assistant.partial_json import MessageFieldStream

_TOKEN_LENGTH = 4


def _tokens_of_reply(message_length: int) -> tuple[str, list[str]]:
    message = ("word \\ \"quoted\" \u00e9\n " * (message_length // 20 + 1))[:message_length]
    document = json.dumps({"message": message, "ef_tables": [], "action_message": []})
    tokens = [
        document[index : index + _TOKEN_LENGTH]
        for index in range(0, len(document), _TOKEN_LENGTH)
    ]
    return message, tokens


def _seconds_to_forward(message_length: int) -> float:
    message, tokens = _tokens_of_reply(message_length)
    message_stream = MessageFieldStream()
    started = time.perf_counter()
    forwarded = "".join(message_stream.feed(token) for token in tokens)
    elapsed = time.perf_counter() - started
    assert forwarded == message
    return elapsed


def _forwards_within(message_length: int, budget_seconds: float) -> bool:
    # Gives up as soon as the budget is spent, so a quadratic regression fails in
    # seconds instead of running to the end of the long reply.
    message, tokens = _tokens_of_reply(message_length)
    message_stream = MessageFieldStream()
    forwarded: list[str] = []
    started = time.perf_counter()
    for token in tokens:
        forwarded.append(message_stream.feed(token))
        if time.perf_counter() - started > budget_seconds:
            return False
    assert "".join(forwarded) == message
    return True


def test_forwarding_a_reply_four_times_longer_costs_about_four_times_more():
    short_length = 5_000
    long_length = short_length * 4
    short_seconds = min(_seconds_to_forward(short_length) for _ in range(3))

    # Linear work needs about 4x the time; re-scanning the whole buffer per token ~16x.
    # The floor keeps a GC pause or a busy CI runner from failing a linear parser,
    # whose 20k-char run takes tens of milliseconds; a quadratic one takes seconds.
    budget_seconds = max(short_seconds * 8, 0.5)
    assert any(_forwards_within(long_length, budget_seconds) for _ in range(3)), (
        f"{long_length} chars took over {budget_seconds:.3f}s "
        f"(8x the {short_seconds:.3f}s of {short_length} chars, floor 0.5s)"
    )
