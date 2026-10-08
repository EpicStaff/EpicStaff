import pytest
from django.contrib.auth.models import AnonymousUser

from rbac.authorship import resolve_author
from rbac.identity.api_keys.principals import SystemServicePrincipal


@pytest.fixture
def author(db, django_user_model):
    return django_user_model.objects.create_user(
        email="author-policy@example.com", password="StrongPass123!"
    )


# ---- resolve_author ----


@pytest.mark.django_db
def test_resolve_author_returns_persisted_user(author):
    assert resolve_author(author) == author


def test_resolve_author_rejects_anonymous_user():
    assert resolve_author(AnonymousUser()) is None


def test_resolve_author_rejects_system_service_principal():
    assert resolve_author(SystemServicePrincipal()) is None


def test_resolve_author_rejects_none():
    assert resolve_author(None) is None


@pytest.mark.django_db
def test_resolve_author_rejects_unsaved_user(django_user_model):
    assert resolve_author(django_user_model(email="unsaved@example.com")) is None
