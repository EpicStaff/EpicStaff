import io

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.fixture
def existing_user(db):
    return get_user_model().objects.create_user(
        email="user@example.com", password="OriginalPass123!"
    )


@pytest.mark.django_db
def test_reset_password_sets_the_new_password(existing_user):
    call_command(
        "reset_password",
        "user@example.com",
        "--password",
        "BrandNewPass456!",
        stdout=io.StringIO(),
    )
    existing_user.refresh_from_db()
    assert existing_user.check_password("BrandNewPass456!")


@pytest.mark.django_db
def test_reset_password_rejects_a_weak_password(existing_user):
    with pytest.raises(CommandError) as exc:
        call_command(
            "reset_password",
            "user@example.com",
            "--password",
            "123",
            stdout=io.StringIO(),
        )
    assert "password" in str(exc.value).lower()
    existing_user.refresh_from_db()
    assert existing_user.check_password("OriginalPass123!")


@pytest.mark.django_db
def test_reset_password_reports_unknown_email(existing_user):
    with pytest.raises(CommandError) as exc:
        call_command(
            "reset_password",
            "nobody@example.com",
            "--password",
            "BrandNewPass456!",
            stdout=io.StringIO(),
        )
    assert "nobody@example.com" in str(exc.value)


@pytest.mark.django_db
def test_generate_prints_the_password_once(existing_user):
    out = io.StringIO()
    call_command("reset_password", "user@example.com", "--generate", stdout=out)
    assert "Generated password" in out.getvalue()
