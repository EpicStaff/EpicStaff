import io

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

PASSWORD = "StrongPass123!"


@pytest.mark.django_db
def test_replaces_every_user_with_a_new_superadmin():
    get_user_model().objects.create_user(email="old@example.com", password=PASSWORD)
    out = io.StringIO()

    call_command("reset_user", "--email", "ops@example.com", "--password", PASSWORD, stdout=out)

    users = get_user_model().objects.all()
    assert [(user.email, user.is_superadmin) for user in users] == [("ops@example.com", True)]
    assert "ops@example.com" in out.getvalue()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("email", "password", "reason"),
    [
        ("---@example.com", PASSWORD, "email: The part before @ must start and end"),
        ("ops@example.com", "1", "password:"),
    ],
    ids=["new-account-email-rule", "password-validators"],
)
def test_invalid_input_fails_before_any_user_is_deleted(email, password, reason):
    get_user_model().objects.create_user(email="old@example.com", password=PASSWORD)

    with pytest.raises(CommandError, match=reason):
        call_command(
            "reset_user", f"--email={email}", f"--password={password}", stdout=io.StringIO()
        )

    assert list(get_user_model().objects.values_list("email", flat=True)) == ["old@example.com"]
