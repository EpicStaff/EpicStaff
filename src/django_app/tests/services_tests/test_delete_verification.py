import pytest

from rbac.exceptions import InvalidVerificationPhraseError
from rbac.governance.delete_verification import DELETE_PHRASE_PREFIX, assert_delete_phrase


def test_prefix_is_the_published_contract():
    assert DELETE_PHRASE_PREFIX == "delete-"


@pytest.mark.parametrize("target", ["Acme Corp", "user@example.com", "delete-inside"])
def test_exact_match_passes(target):
    assert_delete_phrase(f"delete-{target}", target)


@pytest.mark.parametrize(
    "submitted, target",
    [
        (None, "Acme"),
        ("", "Acme"),
        ("delete-", "Acme"),
        ("Acme", "Acme"),
        ("Delete-Acme", "Acme"),
        ("DELETE-Acme", "Acme"),
        ("delete-acme", "Acme"),
        ("delete-Acme ", "Acme"),
        (" delete-Acme", "Acme"),
        ("delete Acme", "Acme"),
        ("delete-Acm", "Acme"),
        ("delete-Acme2", "Acme"),
        (123, "Acme"),
        (["delete-Acme"], "Acme"),
    ],
)
def test_mismatch_raises(submitted, target):
    with pytest.raises(InvalidVerificationPhraseError):
        assert_delete_phrase(submitted, target)


def test_error_shape_does_not_echo_the_phrase():
    with pytest.raises(InvalidVerificationPhraseError) as caught:
        assert_delete_phrase("delete-person@example.com", "other@example.com")

    assert caught.value.status_code == 400
    assert caught.value.default_code == "invalid_verification_phrase"
    assert "example.com" not in str(caught.value.detail)
