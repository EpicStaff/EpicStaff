import re
from dataclasses import dataclass
from typing import Self

from domain.errors import InvalidSearchError

SEARCH_MAX_LENGTH = 100
# "12", "#12", "visitor 12", "Visitor #12": at most 9 digits, so it always fits the INT column.
VISITOR_NUMBER = re.compile(r"(?:visitor\s*)?#?(\d{1,9})", re.IGNORECASE)


@dataclass(frozen=True)
class InboxSearch:
    """What an operator typed into the inbox search, trimmed and with whitespace collapsed.

    It matches a conversation by any of: its visitor number (exactly, on each desk), a signed
    visitor's id (case-insensitive prefix), or its holder's display name (case-insensitive
    substring). An anonymous visitor's subject is a random token and never matches. The case
    is left as typed: the database lowers both sides of each comparison, so one rule decides
    (Python and Postgres disagree on a few letters, such as a final sigma).
    """

    text: str
    # Set when the text names a visitor number.
    visitor_number: int | None

    @classmethod
    def parse(cls, raw: str) -> Self | None:
        """Trim `raw` and collapse its whitespace; None when nothing is left.

        Raises:
            InvalidSearchError: NUL (Postgres text cannot hold it), or longer than
                SEARCH_MAX_LENGTH once trimmed.
        """
        if "\x00" in raw:
            raise InvalidSearchError("The search must not contain NUL (U+0000).")
        text = " ".join(raw.split())
        if not text:
            return None
        if len(text) > SEARCH_MAX_LENGTH:
            raise InvalidSearchError(f"The search must be at most {SEARCH_MAX_LENGTH} characters.")
        number = VISITOR_NUMBER.fullmatch(text)
        return cls(text=text, visitor_number=int(number.group(1)) if number else None)
