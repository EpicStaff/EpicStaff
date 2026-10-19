import pytest
from domain.public_name import PUBLIC_NAME_MAX_LENGTH, normalize_public_name, public_name_key, same_public_name
from tests.factories import make_binding

KEPT = {
    "trimmed": ("  Mike  ", "Mike"),
    "composed to NFC": ("Jose\u0301", "José"),
    "an emoji joined with ZWJ": ("\U0001f469\u200d\U0001f4bb Mike", "\U0001f469\u200d\U0001f4bb Mike"),
    "an emoji with a variation selector": ("❤\ufe0f Team", "❤\ufe0f Team"),
    "right-to-left letters (not overrides)": ("מיכאל", "מיכאל"),
    "CJK": ("小明", "小明"),
    "the longest allowed, once trimmed": ("  " + "a" * PUBLIC_NAME_MAX_LENGTH + "  ", "a" * PUBLIC_NAME_MAX_LENGTH),
}


@pytest.mark.parametrize(("raw", "kept"), KEPT.values(), ids=KEPT.keys())
def test_a_public_name_is_trimmed_composed_and_kept(raw, kept):
    assert normalize_public_name(raw) == kept


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_a_blank_public_name_is_none(raw):
    assert normalize_public_name(raw) is None


REFUSED = {
    "a tab inside": ("Bea\tAgent", "U+0009"),
    "a newline inside": ("Bea\nAgent", "U+000A"),
    "NUL": ("Bea\x00", "U+0000"),
    "a right-to-left override": ("\u202eekiM", "U+202E"),
    "a left-to-right isolate": ("Mike\u2066", "U+2066"),
    "a zero width space": ("Mi\u200bke", "U+200B"),
    "a zero width non-joiner": ("Mi\u200cke", "U+200C"),
    "a soft hyphen": ("Mi\u00adke", "U+00AD"),
    "private use": ("Mike\ue000", "U+E000"),
    "an unassigned code point": ("Mike\u0378", "U+0378"),
    "a line separator": ("Mike\u2028Bea", "U+2028"),
    "a paragraph separator": ("Mike\u2029Bea", "U+2029"),
    "a lone surrogate": ("Mike\ud800", "U+D800"),
}


@pytest.mark.parametrize(("raw", "named"), REFUSED.values(), ids=REFUSED.keys())
def test_a_public_name_refuses_invisible_and_control_characters_and_names_them(raw, named):
    with pytest.raises(ValueError, match=named.replace("+", r"\+")):
        normalize_public_name(raw)


def test_a_public_name_is_at_most_64_characters():
    with pytest.raises(ValueError, match="at most 64"):
        normalize_public_name("a" * (PUBLIC_NAME_MAX_LENGTH + 1))


def test_visitors_see_the_alias_else_the_desks_operator_name():
    desk = make_binding(operator_display_name="Support")
    assert desk.operator_visible_name("Mike") == "Mike"
    assert desk.operator_visible_name(None) == "Support"


@pytest.mark.parametrize(("first", "second", "same"), [("Mike", "mIKE", True), ("Straße", "STRASSE", True), ("Mike", "Mikey", False), ("Ava", "Ava ", False)])
def test_names_visitors_would_read_as_one_compare_equal(first, second, same):
    assert same_public_name(first, second) is same


# Invisible characters are built with chr(), so none sits raw in this file.
ZERO_WIDTH_JOINER, TEXT_STYLE, EMOJI_STYLE, COMBINING_DOT_ABOVE = chr(0x200D), chr(0xFE0E), chr(0xFE0F), chr(0x0307)
FILLERS = [0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180B, 0x180F, 0x2800, 0x3164, 0xFFA0, 0xFE00, 0xFE0D, 0x1BCA0, 0x1BCA3, 0x1D173, 0x1D17A, 0xE0001, 0xE0020, 0xE0100, 0xE01EF, 0xE0FFF]


@pytest.mark.parametrize("code_point", FILLERS, ids=[f"U+{code_point:04X}" for code_point in FILLERS])
def test_a_filler_that_renders_as_nothing_or_a_blank_is_refused(code_point):
    with pytest.raises(ValueError, match=f"U\\+{code_point:04X}"):
        normalize_public_name("Ava" + chr(code_point))


def test_the_emoji_joiner_and_the_text_and_emoji_style_selectors_are_kept():
    technologist = chr(0x1F469) + ZERO_WIDTH_JOINER + chr(0x1F4BB)
    for name in (technologist + " Mike", chr(0x2764) + EMOJI_STYLE + " Team", chr(0x2764) + TEXT_STYLE + " Team"):
        assert normalize_public_name(name) == name


KEYS = {
    "sharp s and double s": ("Stra" + chr(0xDF) + "e", "STRASSE", True),
    "dotted capital I and i with a dot": (chr(0x130) + "pek", "i" + COMBINING_DOT_ABOVE + "pek", True),
    "dotted capital I and plain i": (chr(0x130) + "pek", "ipek", False),
    "dotless i and plain i": (chr(0x131) + "pek", "ipek", False),
    "a joiner copying a name": ("Ava" + ZERO_WIDTH_JOINER, "Ava", True),
    "an emoji selector copying a name": ("Ava" + EMOJI_STYLE, "ava", True),
    "composed and decomposed accents": ("Jos" + chr(0xE9), "Jose" + chr(0x301), True),
    "a different name": ("Mike", "Mikey", False),
}


@pytest.mark.parametrize(("first", "second", "same"), KEYS.values(), ids=KEYS.keys())
def test_one_key_decides_whether_two_names_are_the_same(first, second, same):
    assert (public_name_key(first) == public_name_key(second)) is same
    assert same_public_name(first, second) is same
