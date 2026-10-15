"""The listen-mode transcript buffer: token budget, wake-word input, and the text handed
to the agent (summaries first, then what was said since)."""

import pytest

from domain.services.chat_buffer import ChatBuffer, ChatSummarizedBuffer
from tests.fixtures import FakeTokenizer  # one token per character


@pytest.fixture
def buffer():
    return ChatSummarizedBuffer(FakeTokenizer(), max_buffer_tokens=10, max_chunks_tokens=20)


@pytest.mark.parametrize(
    ("appended", "tokens", "has_room"),
    [([], 0, True), (["ab", "cde"], 5, True), (["a" * 10], 10, False), (["a" * 15], 15, False)],
    ids=["empty", "under-limit", "at-limit", "over-limit"],
)
def test_buffer_counts_tokens_against_its_limit(appended, tokens, has_room):
    buffer = ChatBuffer(FakeTokenizer(), max_buffer_tokens=10)
    for text in appended:
        buffer.append(text)

    assert (len(buffer), buffer.check_free_buffer()) == (tokens, has_room)
    assert buffer.get_buffer() == appended


@pytest.mark.parametrize(
    ("appended", "words"),
    [
        (["hello, world!"], ["hello", "world"]),
        # A spoken "Agent," still matches the wake word "agent".
        (["Stop! Agent, please."], ["stop", "agent", "please"]),
        # Only the latest transcript is checked for the wake word.
        (["agent", "what time is it"], ["what", "time", "is", "it"]),
        ([], []),
    ],
)
def test_last_input_is_the_latest_transcript_as_normalized_words(buffer, appended, words):
    for text in appended:
        buffer.append(text)

    assert buffer.get_last_input() == words


def test_returned_buffers_are_copies(buffer):
    buffer.append("foo")
    buffer.append_chunk("summary")

    buffer.get_buffer().append("mutated")
    buffer.get_chunks().append("mutated")

    assert (buffer.get_buffer(), buffer.get_chunks()) == (["foo"], ["summary"])


def test_summaries_stop_being_added_once_their_budget_is_used(buffer):
    buffer.append_chunk("short")
    assert buffer.check_free_chunks() is True

    buffer.append_chunk("a" * 15)
    buffer.append_chunk("overflow")

    assert buffer.check_free_chunks() is False
    assert buffer.get_chunks() == ["short", "a" * 15]


@pytest.mark.parametrize(
    ("chunks", "inputs", "final"),
    [
        ([], [], ""),
        ([], ["line one", "line two"], "line one\nline two"),
        (["summary one", "summary two"], ["current input"], "summary one\n\nsummary two\n\ncurrent input"),
    ],
    ids=["empty", "inputs-only", "summaries-then-inputs"],
)
def test_final_buffer_puts_summaries_before_what_was_said_since(buffer, chunks, inputs, final):
    for chunk in chunks:
        buffer.append_chunk(chunk)
    for text in inputs:
        buffer.append(text)

    assert buffer.get_final_buffer() == final


def test_flush_chunks_keeps_the_inputs_and_flush_clears_everything(buffer):
    buffer.append("data")
    buffer.append_chunk("summary")

    buffer.flush_chunks()
    assert (buffer.get_buffer(), buffer.get_chunks(), buffer.check_free_chunks()) == (["data"], [], True)

    buffer.append_chunk("summary")
    buffer.flush()
    assert (len(buffer), buffer.get_buffer(), buffer.get_chunks(), buffer.get_last_input()) == (0, [], [], [])
