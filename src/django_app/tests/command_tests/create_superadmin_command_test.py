import io

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from tables.models.rbac_models import Organization, OrganizationUser


@pytest.mark.django_db
def test_creates_superadmin_with_org_and_membership():
    out = io.StringIO()
    call_command(
        "create_superadmin",
        "--email",
        "ops@example.com",
        "--password-stdin",
        stdin=io.StringIO("StrongPass123!\n"),
        stdout=out,
    )

    user = get_user_model().objects.get(email="ops@example.com")
    assert user.is_superadmin is True
    assert OrganizationUser.objects.filter(user=user).count() == 1
    assert "ops@example.com" in out.getvalue()


@pytest.mark.django_db
def test_is_idempotent_when_a_user_already_exists():
    get_user_model().objects.create_user(
        email="existing@example.com", password="StrongPass123!"
    )
    out = io.StringIO()

    # No stdin supplied: proves the existence check runs before any prompt,
    # so an operator is never asked for a password that cannot be used.
    call_command("create_superadmin", "--email", "ops@example.com", stdout=out)

    assert "already exists" in out.getvalue()
    assert get_user_model().objects.count() == 1


@pytest.mark.django_db
def test_org_name_names_the_created_organization():
    call_command(
        "create_superadmin",
        "--email",
        "ops@example.com",
        "--password-stdin",
        "--org-name",
        "Acme Inc",
        stdin=io.StringIO("StrongPass123!\n"),
        stdout=io.StringIO(),
    )
    assert Organization.objects.get(is_default=True).name == "Acme Inc"


@pytest.mark.django_db
def test_org_name_ignored_notice_when_default_org_exists():
    Organization.objects.create(name="Renamed By Operator", is_default=True)
    out = io.StringIO()

    call_command(
        "create_superadmin",
        "--email",
        "ops@example.com",
        "--password-stdin",
        "--org-name",
        "Acme Inc",
        stdin=io.StringIO("StrongPass123!\n"),
        stdout=out,
    )

    assert "ignored" in out.getvalue()
    assert Organization.objects.get(is_default=True).name == "Renamed By Operator"


@pytest.mark.django_db
def test_weak_password_is_rejected_by_the_shared_validator():
    with pytest.raises(CommandError) as exc:
        call_command(
            "create_superadmin",
            "--email",
            "ops@example.com",
            "--password-stdin",
            stdin=io.StringIO("123\n"),
            stdout=io.StringIO(),
        )
    assert "password" in str(exc.value).lower()
    assert get_user_model().objects.count() == 0


@pytest.mark.django_db
def test_empty_stdin_password_is_rejected():
    with pytest.raises(CommandError) as exc:
        call_command(
            "create_superadmin",
            "--email",
            "ops@example.com",
            "--password-stdin",
            stdin=io.StringIO("\n"),
            stdout=io.StringIO(),
        )
    assert "stdin" in str(exc.value).lower()


@pytest.mark.django_db
def test_no_tty_without_password_stdin_is_rejected():
    with pytest.raises(CommandError) as exc:
        call_command(
            "create_superadmin",
            "--email",
            "ops@example.com",
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
        )
    assert "--password-stdin" in str(exc.value)
