import io

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings


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
@override_settings(EMAIL_HOST="")
def test_reset_password_works_without_smtp(existing_user):
    """Guards against gating this command on SMTP: without SMTP it is the only reset path."""
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
def test_reset_password_revokes_the_users_api_keys(existing_user, issue_api_key):
    bystander = get_user_model().objects.create_user(
        email="bystander@example.com", password="OriginalPass123!"
    )
    _, user_key = issue_api_key(user=existing_user)
    _, other_users_key = issue_api_key(user=bystander)
    _, system_key = issue_api_key(user=None)

    call_command(
        "reset_password",
        "user@example.com",
        "--password",
        "BrandNewPass456!",
        stdout=io.StringIO(),
    )

    user_key.refresh_from_db()
    other_users_key.refresh_from_db()
    system_key.refresh_from_db()
    assert user_key.revoked_at is not None
    assert other_users_key.revoked_at is None
    assert system_key.revoked_at is None


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
