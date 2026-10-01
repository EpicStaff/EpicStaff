from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model

UserModel = get_user_model()

backfill_migration = import_module("tables.migrations.0257_backfill_user_display_name")

PASSWORD = "StrongPass123!"


def _user_with_display_name(email, display_name):
    """Create a user, then force the stored display name past the manager's default."""
    user = UserModel.objects.create_user(email=email, password=PASSWORD)
    UserModel.objects.filter(pk=user.pk).update(display_name=display_name)
    return user


def _stored_display_names():
    return dict(UserModel.objects.values_list("email", "display_name"))


@pytest.mark.django_db
def test_null_display_name_is_derived_from_email():
    user = _user_with_display_name("john.smith@acme.com", None)

    backfill_migration.backfill_display_name(django_apps, None)

    user.refresh_from_db()
    assert user.display_name == "John Smith"


@pytest.mark.django_db
@pytest.mark.parametrize("blank_display_name", ["", "   ", "\t\n"])
def test_blank_display_name_is_derived_from_email(blank_display_name):
    user = _user_with_display_name("mary_ann-lee@acme.com", blank_display_name)

    backfill_migration.backfill_display_name(django_apps, None)

    user.refresh_from_db()
    assert user.display_name == "Mary Ann Lee"


@pytest.mark.django_db
def test_local_part_without_letters_falls_back_to_raw_local_part():
    user = _user_with_display_name("=2+5@acme.com", None)

    backfill_migration.backfill_display_name(django_apps, None)

    user.refresh_from_db()
    assert user.display_name == "=2+5"


@pytest.mark.django_db
def test_symbols_split_and_casing_is_normalized_in_backfilled_name():
    user = _user_with_display_name("JOHN!smith+Jr@acme.com", None)

    backfill_migration.backfill_display_name(django_apps, None)

    user.refresh_from_db()
    assert user.display_name == "John Smith Jr"


@pytest.mark.django_db
def test_digits_are_dropped_from_backfilled_name():
    user = _user_with_display_name("shark345@gmail.com", None)

    backfill_migration.backfill_display_name(django_apps, None)

    user.refresh_from_db()
    assert user.display_name == "Shark"


@pytest.mark.django_db
def test_existing_display_name_is_not_overwritten():
    named = _user_with_display_name("jane.doe@acme.com", "Jane")
    padded = _user_with_display_name("pad.ded@acme.com", "  Jane  ")

    backfill_migration.backfill_display_name(django_apps, None)

    named.refresh_from_db()
    padded.refresh_from_db()
    assert named.display_name == "Jane"
    assert padded.display_name == "  Jane  "


@pytest.mark.django_db
def test_backfill_leaves_updated_at_unchanged():
    user = _user_with_display_name("john.smith@acme.com", None)
    user.refresh_from_db()
    updated_at_before = user.updated_at

    backfill_migration.backfill_display_name(django_apps, None)

    user.refresh_from_db()
    assert user.display_name == "John Smith"
    assert user.updated_at == updated_at_before


@pytest.mark.django_db
def test_backfill_covers_more_rows_than_one_batch(monkeypatch):
    monkeypatch.setattr(backfill_migration, "BATCH_SIZE", 2)
    emails = [f"user.{letter}@acme.com" for letter in "abcde"]
    for email in emails:
        _user_with_display_name(email, None)

    backfill_migration.backfill_display_name(django_apps, None)

    stored = _stored_display_names()
    assert [stored[email] for email in emails] == [
        f"User {letter.upper()}" for letter in "abcde"
    ]


@pytest.mark.django_db
def test_backfill_is_idempotent():
    _user_with_display_name("john.smith@acme.com", None)
    backfill_migration.backfill_display_name(django_apps, None)
    after_first_run = _stored_display_names()

    backfill_migration.backfill_display_name(django_apps, None)

    assert _stored_display_names() == after_first_run


@pytest.mark.django_db
def test_reverse_migration_changes_nothing():
    _user_with_display_name("john.smith@acme.com", None)
    _user_with_display_name("jane.doe@acme.com", "Jane")
    backfill_migration.backfill_display_name(django_apps, None)
    before_reverse = _stored_display_names()
    (run_python,) = backfill_migration.Migration.operations

    run_python.reverse_code(django_apps, None)

    assert run_python.reversible
    assert _stored_display_names() == before_reverse
