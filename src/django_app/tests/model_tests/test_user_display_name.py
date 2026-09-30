import pytest

from tables.models.user import DISPLAY_NAME_MAX_LENGTH, display_name_from_email


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("john.smith@acme.com", "John Smith"),
        ("mary_ann@x.io", "Mary Ann"),
        ("mary-ann@x.io", "Mary Ann"),
        ("mary_ann-lee@x.io", "Mary Ann Lee"),
        ("john.smith+test@acme.com", "John Smith"),
        ("john+a+b@acme.com", "John"),
        ("jsmith92@acme.com", "Jsmith92"),
        ("92jsmith@acme.com", "92jsmith"),
        ("a@x.io", "A"),
        ("john..smith__lee--x@acme.com", "John Smith Lee X"),
        (".john.@acme.com", "John"),
        ("mcDonald@x.io", "McDonald"),
        ("jean.mcDonald@x.io", "Jean McDonald"),
        ("JOHN.SMITH@ACME.COM", "JOHN SMITH"),
    ],
)
def test_display_name_from_email_formats_local_part(email, expected):
    assert display_name_from_email(email) == expected


def test_display_name_uses_last_at_sign_as_domain_separator():
    assert display_name_from_email('"a@b".c@x.io') == '"a@b" C'


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("+tag@x.com", "+tag"),
        ("..@x.com", ".."),
        ("._-@x.com", "._-"),
        (".+tag@x.com", ".+tag"),
    ],
)
def test_display_name_falls_back_to_raw_local_part(email, expected):
    assert display_name_from_email(email) == expected


def test_display_name_falls_back_to_whole_email_when_local_part_empty():
    assert display_name_from_email("@x.com") == "@x.com"


def test_display_name_uses_whole_string_without_at_sign():
    assert display_name_from_email("john.smith") == "John Smith"


def test_display_name_is_truncated_to_max_length():
    email = "a" * 300 + "@x.io"

    display_name = display_name_from_email(email)

    assert display_name == "A" + "a" * (DISPLAY_NAME_MAX_LENGTH - 1)


def test_display_name_truncation_strips_trailing_space():
    # Piece boundary lands exactly on the cut: 254 chars, then a separator.
    email = "a" * 254 + ".bbbbbb@x.io"

    display_name = display_name_from_email(email)

    assert len(display_name) <= DISPLAY_NAME_MAX_LENGTH
    assert not display_name.endswith(" ")
    assert display_name == "A" + "a" * 253
