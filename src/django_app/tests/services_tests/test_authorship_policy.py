import pytest
from django.contrib.auth.models import AnonymousUser

from rbac.authorship import claim_authorship, resolve_author
from rbac.identity.api_keys.principals import SystemServicePrincipal
from tables.models import Label

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def author(db, django_user_model):
    return django_user_model.objects.create_user(
        email="author-policy@example.com", password="StrongPass123!"
    )


@pytest.fixture
def other_user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="other-policy@example.com", password="StrongPass123!"
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


# ---- claim_authorship ----


@pytest.mark.django_db
def test_claim_authorship_sets_author_when_empty(acme, author):
    label = Label.objects.create(name="claim-empty", org=acme)

    assert claim_authorship(label, author) is True
    assert label.created_by_id == author.id
    label.refresh_from_db()
    assert label.created_by_id is None


@pytest.mark.django_db
def test_claim_authorship_keeps_existing_author(acme, author, other_user):
    label = Label.objects.create(name="claim-set", org=acme, created_by=author)

    assert claim_authorship(label, other_user) is False
    assert label.created_by_id == author.id


@pytest.mark.django_db
@pytest.mark.parametrize(
    "acting_user",
    [None, AnonymousUser(), SystemServicePrincipal()],
    ids=["none", "anonymous", "system-principal"],
)
def test_claim_authorship_ignores_unresolvable_user(acme, acting_user):
    label = Label.objects.create(name="claim-unresolvable", org=acme)

    assert claim_authorship(label, acting_user) is False
    assert label.created_by_id is None
