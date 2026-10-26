from dataclasses import dataclass


@dataclass(frozen=True)
class UidRange:
    """`PLUGINS_NODE_UID_RANGE`: the only UIDs the launcher switches to for a plugin."""

    first: int
    last: int

    MINIMUM_FIRST = 10001
    MAXIMUM_LAST = 59999
    MINIMUM_SIZE = 10

    @classmethod
    def parse(cls, text: str) -> "UidRange":
        """Parse `<start>-<end>`, with the bounds django_app's start-up check applies.

        Raises:
            ValueError: The text is not such a range.
        """
        first_text, separator, last_text = text.strip().partition("-")
        if not separator or not first_text.isdigit() or not last_text.isdigit():
            raise ValueError(f"PLUGINS_NODE_UID_RANGE={text!r} is not <start>-<end>")
        first, last = int(first_text), int(last_text)
        if not cls.MINIMUM_FIRST <= first <= last <= cls.MAXIMUM_LAST:
            raise ValueError(
                f"PLUGINS_NODE_UID_RANGE={text!r} must satisfy "
                f"{cls.MINIMUM_FIRST - 1} < start <= end < {cls.MAXIMUM_LAST + 1}"
            )
        if last - first + 1 < cls.MINIMUM_SIZE:
            raise ValueError(f"PLUGINS_NODE_UID_RANGE={text!r} has fewer than 10 ids")
        return cls(first, last)

    def __contains__(self, uid: object) -> bool:
        return isinstance(uid, int) and self.first <= uid <= self.last
