from enum import StrEnum


class IdentityMode(StrEnum):
    ANONYMOUS = "anonymous"
    SIGNED = "signed"


class OnBudgetExhausted(StrEnum):
    REPLY = "reply"
    HANDOFF = "handoff"


class Mode(StrEnum):
    BOT = "bot"
    AWAITING_HUMAN = "awaiting_human"
    HUMAN = "human"


class ConversationStatus(StrEnum):
    """Open or closed, apart from the mode; a closed conversation never reopens."""

    OPEN = "open"
    CLOSED = "closed"


class CloseReason(StrEnum):
    # An operator resolved it.
    RESOLVED = "resolved"
    # The visitor started a new chat.
    ENDED = "ended"
    # The desk's close-after timer.
    INACTIVE = "inactive"


class BindingStyle(StrEnum):
    """Support closes on Resolve, on the visitor's new chat or after inactivity; Ongoing never
    closes on its own, so one thread carries the visitor's whole history."""

    SUPPORT = "support"
    ONGOING = "ongoing"


class OnResponseTimeout(StrEnum):
    """What a desk does once a visitor has waited past its response time."""

    # Back to the bot, with the desk's notice.
    HANDBACK = "handback"
    # Nothing here: the inbox marks the conversation overdue.
    OVERDUE = "overdue"
    WAIT = "wait"


class InboxSection(StrEnum):
    """The operator inbox's lists.

    Waiting, In progress, Bot, Test and Closed never share a row; only Test lists tests, open
    and closed alike.

    Waiting: a visitor waits for a person (`visitor_waiting_since` set): handed off and not
    answered yet, or held and the visitor wrote after the last operator reply, or held since a
    take over straight from the bot that found the visitor's message or a run-failure notice
    last. In progress: open, held by an operator with nobody waiting, and at least one message:
    the operator replied after the visitor's last message, or took it over from the bot after
    the bot answered and the visitor has not written since. Each desk's inactivity rules bound
    them: a desk set to hand back returns a visitor waiting past its response time to the bot,
    and a Support desk closes a conversation silent for its close-after time. Otherwise a
    conversation stays until someone acts: on an Ongoing desk, In progress always does, and
    Waiting does unless the desk hands back.

    Bot: open, with the bot, at least one message. Test: operators' test conversations with at
    least one message, whatever their state. Closed: closed, at least one message, not a test.
    Human, every open handed-off conversation, overlaps Waiting and In progress; it stays until
    every client lists those instead.
    """

    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    HUMAN = "human"
    BOT = "bot"
    TEST = "test"
    CLOSED = "closed"

    @property
    def key_field(self) -> str:
        """The `Conversation` field the section is ordered by, then by id."""
        return _SECTION_KEYS[self]


_SECTION_KEYS = {
    InboxSection.WAITING: "visitor_waiting_since",
    InboxSection.IN_PROGRESS: "last_message_at",
    InboxSection.HUMAN: "handoff_at",
    InboxSection.BOT: "last_message_at",
    InboxSection.TEST: "last_message_at",
    InboxSection.CLOSED: "closed_at",
}


class InboxOrder(StrEnum):
    """Newest or oldest activity first. Waiting and Human are queues and ignore it, and Closed
    always lists the most recently closed first."""

    NEWEST = "newest"
    OLDEST = "oldest"


class RunState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    OPERATOR = "operator"
    SYSTEM = "system"


class Stream(StrEnum):
    CONVERSATION = "conversation"
    INBOX = "inbox"


class SubmitState(StrEnum):
    PROCESSING = "processing"
    FORWARDED_TO_OPERATOR = "forwarded_to_operator"
    BUDGET_EXHAUSTED = "budget_exhausted"


TERMINAL_RUN_STATUSES = frozenset({"end", "error", "stop", "expired"})
