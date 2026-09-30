import pytest

from tables.models.user import DISPLAY_NAME_MAX_LENGTH, display_name_from_email


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("john.smith@acme.com", "John Smith"),
        ("mary_ann@x.io", "Mary Ann"),
        ("mary-ann@x.io", "Mary Ann"),
        ("mary_ann-lee@x.io", "Mary Ann Lee"),
        ("mary-jane.watson@gmail.com", "Mary Jane Watson"),
        ("john.smith.jr@gmail.com", "John Smith Jr"),
        ("a@x.io", "A"),
        ("j.r.r.tolkien@gmail.com", "J R R Tolkien"),
        ("john..smith__lee--x@acme.com", "John Smith Lee X"),
        (".john.@acme.com", "John"),
        ("john@localhost", "John"),
        ("de.la.cruz@x.com", "De La Cruz"),
        ("info@acme.com", "Info"),
        ("no-reply@acme.com", "No Reply"),
    ],
)
def test_display_name_splits_on_dots_underscores_and_hyphens(email, expected):
    assert display_name_from_email(email) == expected


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("john!#$&*smith@gmail.com", "John Smith"),
        ("john%smith@gmail.com", "John Smith"),
        ("john/n@gmail.com", "John N"),
        ("john._-smith@gmail.com", "John Smith"),
        ("john+smith@gmail.com", "John Smith"),
        ("john+newsletter@gmail.com", "John Newsletter"),
        ("+john@gmail.com", "John"),
        ("john.smith+test@acme.com", "John Smith Test"),
        ("__proto__@x.com", "Proto"),
        ('"a@b".c@x.io', "A B C"),
    ],
)
def test_display_name_splits_on_any_symbol(email, expected):
    assert display_name_from_email(email) == expected


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("o'brien@gmail.com", "O'brien"),
        ("'john'@gmail.com", "John"),
    ],
)
def test_display_name_keeps_inner_apostrophes(email, expected):
    assert display_name_from_email(email) == expected


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("shark345@gmail.com", "Shark"),
        ("123john@gmail.com", "John"),
        ("j0hn@gmail.com", "Jhn"),
        ("jo123hn@gmail.com", "John"),
        ("john.1990.smith@gmail.com", "John Smith"),
        ("john2Smith@gmail.com", "John Smith"),
        ("007bond@acme.com", "Bond"),
    ],
)
def test_display_name_drops_digits(email, expected):
    assert display_name_from_email(email) == expected


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("JOHN.SMITH@ACME.COM", "John Smith"),
        ("jOhN.sMiTh@gmail.com", "John Smith"),
        ("JohnSmith@gmail.com", "John Smith"),
        ("johnSmith@gmail.com", "John Smith"),
        ("JohnSmithJr@gmail.com", "John Smith Jr"),
        ("toString@x.com", "To String"),
        ("mcDonald@x.io", "Mc Donald"),
        ("johnsmith@gmail.com", "Johnsmith"),
        ("JOHNSMITH@gmail.com", "Johnsmith"),
        ("iPhone@gmail.com", "Iphone"),
        ("NaN@x.com", "Nan"),
    ],
)
def test_display_name_recases_words_and_splits_camel_case(email, expected):
    assert display_name_from_email(email) == expected


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("a" * 30 + "@gmail.com", "Aaaaa"),
        ("joooooooohn@x.com", "Jooooohn"),
        ("jooooohn@x.com", "Jooooohn"),
        ("AAAAAAAA.bbbbbbbbb@x.com", "Aaaaa Bbbbb"),
    ],
)
def test_display_name_cuts_repeated_letters_to_five(email, expected):
    assert display_name_from_email(email) == expected


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("12345@x.com", "12345"),
        ("380501234567@gmail.com", "380501234567"),
        ("1.2.3@gmail.com", "1.2.3"),
        ("=2+5@x.com", "=2+5"),
        ("-1+1@x.com", "-1+1"),
        ("${7*7}@x.com", "${7*7}"),
        ("{{7*7}}@x.com", "{{7*7}}"),
        ("---@gmail.com", "---"),
        ("'''@x.com", "'''"),
    ],
)
def test_display_name_without_letters_keeps_raw_local_part(email, expected):
    assert display_name_from_email(email) == expected


def test_display_name_falls_back_to_whole_email_when_local_part_empty():
    assert display_name_from_email("@x.com") == "@x.com"


def test_display_name_uses_whole_string_without_at_sign():
    assert display_name_from_email("john.smith") == "John Smith"


def test_display_name_is_truncated_to_max_length():
    email = "ab" * 150 + "@x.io"

    display_name = display_name_from_email(email)

    assert display_name == "Ab" + "ab" * 126 + "a"


def test_display_name_truncation_strips_trailing_space():
    # Word boundary lands exactly on the cut: 254 chars, then a separator.
    email = "ab" * 127 + ".cd@x.io"

    display_name = display_name_from_email(email)

    assert display_name == "Ab" + "ab" * 126
