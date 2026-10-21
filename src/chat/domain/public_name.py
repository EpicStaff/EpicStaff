"""Names visitors see: a desk's bot and operator names, and an operator's alias on a desk."""

import unicodedata
from itertools import chain

PUBLIC_NAME_MAX_LENGTH = 64
# Full case folding maps one character to at most three (U+0390 becomes three), so a key of a
# name of PUBLIC_NAME_MAX_LENGTH characters fits in this.
PUBLIC_NAME_KEY_MAX_LENGTH = 3 * PUBLIC_NAME_MAX_LENGTH
# What a name shown to visitors cannot contain, by kind: controls, surrogates, private use,
# unassigned code points, line and paragraph separators, and invisible formatting, which includes
# the bidirectional overrides that make text read backwards.
_REFUSED_CATEGORIES = frozenset({"Cc", "Cs", "Co", "Cn", "Zl", "Zp", "Cf"})
# Kept although invisible: emoji need them. The zero width joiner (U+200D) builds sequences such
# as a technologist; variation selectors 15 and 16 (U+FE0E, U+FE0F) pick text or emoji style.
_EMOJI_JOINERS = frozenset({"\u200d", "\ufe0e", "\ufe0f"})
# Refused one by one: characters of allowed kinds that render as nothing or as a blank, so a name
# with one added reads exactly like the name without it.
_INVISIBLE_FILLERS = frozenset(
    chr(code_point)
    for code_point in chain(
        (0x034F,),  # combining grapheme joiner
        (0x115F, 0x1160),  # Hangul choseong and jungseong fillers
        (0x17B4, 0x17B5),  # Khmer inherent vowels
        range(0x180B, 0x1810),  # Mongolian free variation selectors and vowel separator
        (0x2800,),  # braille pattern blank
        (0x3164, 0xFFA0),  # Hangul filler, halfwidth Hangul filler
        range(0xFE00, 0xFE0E),  # variation selectors 1-14 (15 and 16 are emoji joiners)
        range(0x1BCA0, 0x1BCA4),  # shorthand format controls
        range(0x1D173, 0x1D17B),  # musical symbol formatting
        range(0xE0000, 0xE1000),  # tags, variation selectors 17-256 and their reserved block
    )
)


def is_refused_in_public_name(character: str) -> bool:
    """Whether a name shown to visitors may not contain `character`."""
    if character in _EMOJI_JOINERS:
        return False
    return character in _INVISIBLE_FILLERS or unicodedata.category(character) in _REFUSED_CATEGORIES


def normalize_public_name(value: str) -> str | None:
    """`value` in NFC and trimmed; None when nothing is left (a blank alias clears it).

    Unassigned means unassigned in this Python's Unicode version, so a character newer than it
    is refused until the runtime catches up.

    Raises:
        ValueError: Longer than PUBLIC_NAME_MAX_LENGTH once trimmed, or a refused character;
            the message names it.
    """
    name = unicodedata.normalize("NFC", value).strip()
    if not name:
        return None
    if len(name) > PUBLIC_NAME_MAX_LENGTH:
        raise ValueError(f"Must be at most {PUBLIC_NAME_MAX_LENGTH} characters.")
    for character in name:
        if is_refused_in_public_name(character):
            raise ValueError(f"Must be plain text: U+{ord(character):04X} is not allowed.")
    return name


def public_name_key(name: str) -> str:
    """What two names visitors would read as one have in common; the only "same name" rule.

    The emoji joiners are dropped (they render as nothing next to letters), then the name is
    case folded in full (so "Straße" and "STRASSE" meet) and put in NFC both before and after
    (folding can leave a letter and its accent apart). Locale-independent, unlike a database's
    lower().
    """
    visible = "".join(character for character in name if character not in _EMOJI_JOINERS)
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", visible).casefold())


def same_public_name(first: str, second: str) -> bool:
    """Whether visitors would read two names as one: their keys are equal."""
    return public_name_key(first) == public_name_key(second)
