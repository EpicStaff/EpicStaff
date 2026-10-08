from datetime import timedelta
from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

backfill_migration = import_module(
    "tables.migrations.0259_user_quickstart_tour_completed_at"
)


@pytest.mark.django_db
def test_backfill_marks_every_existing_user_as_tour_completed(django_user_model):
    first_user = django_user_model.objects.create_user(email="first@backfill.test")
    second_user = django_user_model.objects.create_user(email="second@backfill.test")

    backfill_migration.mark_existing_users_tour_completed(django_apps, None)

    first_user.refresh_from_db()
    second_user.refresh_from_db()
    assert first_user.quickstart_tour_completed_at is not None
    assert second_user.quickstart_tour_completed_at is not None


@pytest.mark.django_db
def test_backfill_keeps_an_existing_completion_timestamp(django_user_model):
    earlier = timezone.now() - timedelta(days=30)
    user = django_user_model.objects.create_user(
        email="done@backfill.test", quickstart_tour_completed_at=earlier
    )

    backfill_migration.mark_existing_users_tour_completed(django_apps, None)

    user.refresh_from_db()
    assert user.quickstart_tour_completed_at == earlier
