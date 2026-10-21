import pytest
from django.contrib.auth import get_user_model

from rbac.exceptions import FormValidationError
from rbac.identity.passwords.writer import PasswordWriter

ACCOUNT_EMAIL = "jane.doe.kowalska@example.com"
ORIGINAL_PASSWORD = "OriginalPass123!"


@pytest.fixture
def account(db):
    return get_user_model().objects.create_user(email=ACCOUNT_EMAIL, password=ORIGINAL_PASSWORD)


@pytest.mark.django_db
def test_set_rejects_password_like_the_accounts_email_without_saving(account):
    with pytest.raises(FormValidationError) as error:
        PasswordWriter().set(account, ACCOUNT_EMAIL)

    assert error.value.errors == [
        {
            "field": "new_password",
            "value": "***",
            "reason": "The password is too similar to the email.",
        }
    ]
    account.refresh_from_db()
    assert account.check_password(ORIGINAL_PASSWORD)


@pytest.mark.django_db
def test_set_saves_a_strong_password(account):
    PasswordWriter().set(account, "BrandNewPass456!")

    account.refresh_from_db()
    assert account.check_password("BrandNewPass456!")
