# Chat Admin "Append turn" node: adds one question and its answer to the
# conversation record, which the next node stores under the conversation id.
#
# Record: {title, turns, messages: [{role, content, at}], started_at, updated_at,
# conversation_id}. `turns` counts every question asked in the conversation, also
# those whose messages were dropped to keep the record small.
import json
from datetime import UTC, datetime

# The key-value table takes values up to 256 KiB; stay well below it.
MAX_RECORD_BYTES = 200_000
MAX_TITLE_CHARS = 80
UNTITLED = "New conversation"
ELLIPSIS = "…"


def main(conversation_id, conversation, question, answer):
    now = _now()
    previous = conversation if isinstance(conversation, dict) else {}
    messages = [
        dict(message) for message in previous.get("messages") or [] if isinstance(message, dict)
    ]
    question = _text(question)
    messages.append({"role": "user", "content": question, "at": now})
    messages.append({"role": "assistant", "content": _text(answer), "at": now})
    record = {
        "title": previous.get("title") or _title(question),
        "turns": _count(previous.get("turns")) + 1,
        "messages": messages,
        "started_at": previous.get("started_at") or now,
        "updated_at": now,
        "conversation_id": conversation_id,
    }
    return _fit(record)


def _fit(record):
    """Drop the oldest question/answer pairs until the record fits.

    If the newest pair alone is still too big, shorten its answer, then its question.
    """
    messages = record["messages"]
    while _size(record) > MAX_RECORD_BYTES and len(messages) > 2:
        del messages[:2]
    for message in reversed(messages):
        overflow = _size(record) - MAX_RECORD_BYTES
        if overflow <= 0:
            break
        message["content"] = _shorten(message["content"], overflow)
    return record


def _shorten(text, overflow):
    # Cut by UTF-8 bytes: a character never takes fewer bytes in the JSON than in
    # UTF-8, so the JSON shrinks by at least what is cut, and the ellipsis puts back
    # exactly its own length. A character split by the cut is dropped whole.
    encoded = text.encode("utf-8")
    keep = len(encoded) - overflow - len(ELLIPSIS.encode("utf-8"))
    if keep <= 0:
        return ""
    return encoded[:keep].decode("utf-8", errors="ignore") + ELLIPSIS


def _size(record):
    # Measured the way the key-value table measures a value.
    return len(json.dumps(record, ensure_ascii=False).encode("utf-8"))


def _title(question):
    title = " ".join(question.split())
    if not title:
        return UNTITLED
    if len(title) <= MAX_TITLE_CHARS:
        return title
    return title[: MAX_TITLE_CHARS - len(ELLIPSIS)].rstrip() + ELLIPSIS


def _text(value):
    return "" if value is None else str(value)


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _now():
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
