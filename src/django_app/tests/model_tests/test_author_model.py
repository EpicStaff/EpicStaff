import pytest
from django.apps import apps
from django.core import checks
from rest_framework.exceptions import APIException

from rbac.authorship.checks import check_author_models
from rbac.authorship.registry import author_tracked_models
from rbac.exceptions import AuthorChangeForbiddenError
from rbac.models import AuthorModel, OrgScopedModel
from tables.models import Graph, GraphNote, Label

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def author(db, django_user_model):
    return django_user_model.objects.create_user(
        email="author-model@example.com", password="StrongPass123!"
    )


@pytest.fixture
def other_user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="other-model@example.com", password="StrongPass123!"
    )


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="author-model-flow", org=acme)


def _note(graph, content, **fields):
    return GraphNote.objects.create(graph=graph, content=content, **fields)


# ---- immutability guard ----


@pytest.mark.django_db
def test_changing_set_author_to_another_user_raises(acme_graph, author, other_user):
    _note(acme_graph, "guarded", created_by=author)
    note = GraphNote.objects.get(content="guarded")

    note.created_by = other_user
    with pytest.raises(AuthorChangeForbiddenError):
        note.save()

    assert GraphNote.objects.get(pk=note.pk).created_by_id == author.id


@pytest.mark.django_db
def test_changing_author_on_instance_that_saved_it_raises(acme_graph, author, other_user):
    note = _note(acme_graph, "guarded-in-memory", created_by=author)

    note.created_by = other_user
    with pytest.raises(AuthorChangeForbiddenError):
        note.save()


@pytest.mark.django_db
def test_clearing_set_author_is_allowed(acme_graph, author):
    _note(acme_graph, "clearable", created_by=author)
    note = GraphNote.objects.get(content="clearable")

    note.created_by = None
    note.save()

    assert GraphNote.objects.get(pk=note.pk).created_by_id is None


@pytest.mark.django_db
def test_setting_author_on_row_without_author_is_allowed(acme_graph, author):
    _note(acme_graph, "unauthored")
    note = GraphNote.objects.get(content="unauthored")

    note.created_by = author
    note.save()

    assert GraphNote.objects.get(pk=note.pk).created_by_id == author.id


@pytest.mark.django_db
def test_resaving_same_author_is_allowed(acme_graph, author):
    _note(acme_graph, "same-author", created_by=author)
    note = GraphNote.objects.get(content="same-author")

    note.content = "same-author-edited"
    note.save()

    assert GraphNote.objects.get(pk=note.pk).content == "same-author-edited"


@pytest.mark.django_db
def test_guard_applies_after_deferred_author_is_loaded(acme_graph, author, other_user):
    _note(acme_graph, "deferred", created_by=author)
    note = GraphNote.objects.defer("created_by").get(content="deferred")

    assert note.created_by_id == author.id
    note.created_by = other_user
    with pytest.raises(AuthorChangeForbiddenError):
        note.save()


@pytest.mark.django_db
def test_author_set_after_refresh_from_db_follows_database_author(
    acme_graph, author, other_user
):
    note = _note(acme_graph, "refreshed", created_by=author)
    GraphNote.objects.filter(pk=note.pk).update(created_by=None)

    note.refresh_from_db()
    note.created_by = other_user
    note.save()

    assert GraphNote.objects.get(pk=note.pk).created_by_id == other_user.id


@pytest.mark.django_db
def test_save_with_update_fields_excluding_author_does_not_move_guard(
    acme_graph, author, other_user
):
    note = _note(acme_graph, "partial", created_by=author)

    note.created_by = None
    note.save(update_fields=["content"])
    note.created_by = other_user
    with pytest.raises(AuthorChangeForbiddenError):
        note.save()


def test_author_change_error_is_a_server_error_not_an_api_response():
    assert not issubclass(AuthorChangeForbiddenError, APIException)


# ---- content hash ----


@pytest.mark.django_db
def test_content_hash_ignores_author(acme_graph, author, other_user):
    first = GraphNote(graph=acme_graph, content="hash-note", created_by=author)
    second = GraphNote(graph=acme_graph, content="hash-note", created_by=other_user)

    assert first.generate_hash() == second.generate_hash()


# ---- registry ----


def test_org_scoped_model_is_not_an_author_model():
    assert not issubclass(OrgScopedModel, AuthorModel)


def test_registry_covers_both_author_families():
    lookups = dict(author_tracked_models())

    assert lookups[GraphNote] == "graph__org_id"
    assert lookups[Graph] == "org_id"
    assert lookups[Label] == "org_id"


def test_registry_lists_every_concrete_author_and_org_scoped_model():
    expected = {
        model
        for model in apps.get_models()
        if issubclass(model, (AuthorModel, OrgScopedModel))
        and model._meta.get_field("created_by").model is model
    }

    assert {model for model, _ in author_tracked_models()} == expected


@pytest.mark.django_db
def test_every_registered_org_lookup_resolves():
    for model, org_lookup in author_tracked_models():
        assert org_lookup is not None, model.__name__
        model._base_manager.filter(**{org_lookup: 1}).exists()


# ---- system check ----


def test_system_check_passes_for_configured_author_models():
    assert check_author_models(app_configs=None) == []


def test_system_check_reports_author_model_without_org_lookup(monkeypatch):
    monkeypatch.setattr(GraphNote, "author_org_lookup", None)

    errors = check_author_models(app_configs=None)

    assert [error.id for error in errors] == ["rbac.E001"]
    assert errors[0].obj is GraphNote
    assert "GraphNote" in errors[0].msg


def test_system_check_is_registered(monkeypatch):
    monkeypatch.setattr(GraphNote, "author_org_lookup", None)

    errors = checks.run_checks(tags=[checks.Tags.models])

    assert "rbac.E001" in {error.id for error in errors}
