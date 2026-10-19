import pytest
from domain.errors import InvalidSearchError
from domain.search import SEARCH_MAX_LENGTH, InboxSearch
from infrastructure.database.repositories import _like_escaped

PARSED = {
    "a number": ("12", "12", 12),
    "with a hash": ("#12", "#12", 12),
    "visitor and a number": ("Visitor 12", "Visitor 12", 12),
    "visitor, hash, no space": ("VISITOR#7", "VISITOR#7", 7),
    "trimmed and collapsed": ("  Visitor \t  #  ", "Visitor #", None),
    "nine digits": ("123456789", "123456789", 123456789),
    "ten digits is text": ("1234567890", "1234567890", None),
    # The case stays as typed: Postgres lowers both sides, Python would lower these differently.
    "a word": ("  Ada   LOVELACE ", "Ada LOVELACE", None),
    "a dotted capital I": ("\u0130PEK", "\u0130PEK", None),
    "a final sigma": ("\u039f\u0394\u039f\u03a3", "\u039f\u0394\u039f\u03a3", None),
    "a signed id": ("Customer-42", "Customer-42", None),
    "number inside text": ("visitor 12 b", "visitor 12 b", None),
    "wildcards stay as typed": ("50%_off", "50%_off", None),
}


@pytest.mark.parametrize(("raw", "text", "number"), PARSED.values(), ids=PARSED.keys())
def test_parse_normalizes_and_reads_a_visitor_number(raw, text, number):
    assert InboxSearch.parse(raw) == InboxSearch(text=text, visitor_number=number)


@pytest.mark.parametrize("raw", ["", "   ", "\t\n "])
def test_a_blank_search_is_no_search(raw):
    assert InboxSearch.parse(raw) is None


def test_the_length_limit_counts_after_normalizing():
    assert InboxSearch.parse("a" * SEARCH_MAX_LENGTH).text == "a" * SEARCH_MAX_LENGTH
    assert InboxSearch.parse("  " + "a b " * 25 + "  ").text == ("a b " * 25).strip()  # 99 once collapsed
    with pytest.raises(InvalidSearchError, match="at most 100"):
        InboxSearch.parse("a" * (SEARCH_MAX_LENGTH + 1))


def test_nul_is_refused():
    with pytest.raises(InvalidSearchError, match="NUL"):
        InboxSearch.parse("ada\x00")


@pytest.mark.parametrize(("text", "escaped"), [("ada", "ada"), ("50%", "50\\%"), ("a_b", "a\\_b"), ("back\\slash", "back\\\\slash"), ("%_\\", "\\%\\_\\\\")])
def test_like_wildcards_are_taken_literally(text, escaped):
    assert _like_escaped(text) == escaped
