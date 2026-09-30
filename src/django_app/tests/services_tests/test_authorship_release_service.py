import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from agents.models import AgentDefinition
from agents.models.surface_models import Surface
from rbac.governance.authorship import AuthorshipReleaseService
from rbac.models import OrganizationUser
from tables.models import Graph, GraphNote, Label, LLMModel, StorageFile

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def author(db, django_user_model):
    return django_user_model.objects.create_user(
        email="author-release@example.com", password="StrongPass123!"
    )


@pytest.fixture
def other_user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="other-release@example.com", password="StrongPass123!"
    )


@pytest.mark.django_db
def test_release_clears_author_only_in_target_org(acme, beta, author, other_user):
    acme_label = Label.objects.create(name="acme-label", org=acme, created_by=author)
    acme_graph = Graph.objects.create(name="acme-flow", org=acme, created_by=author)
    deleted_graph = Graph.objects.create(
        name="acme-deleted-flow",
        org=acme,
        created_by=author,
        is_soft_deleted=True,
        soft_deleted_at=timezone.now(),
    )
    beta_graph = Graph.objects.create(name="beta-flow", org=beta, created_by=author)
    colleague_graph = Graph.objects.create(
        name="acme-colleague-flow", org=acme, created_by=other_user
    )

    acme_note = GraphNote.objects.create(graph=acme_graph, content="acme", created_by=author)
    beta_note = GraphNote.objects.create(graph=beta_graph, content="beta", created_by=author)
    colleague_note = GraphNote.objects.create(
        graph=acme_graph, content="colleague", created_by=other_user
    )

    released = AuthorshipReleaseService().release(user_id=author.id, org_id=acme.id)

    assert released == 4
    assert Label.objects.get(pk=acme_label.pk).created_by_id is None
    assert Graph.all_objects.get(pk=acme_graph.pk).created_by_id is None
    assert Graph.all_objects.get(pk=deleted_graph.pk).created_by_id is None
    assert GraphNote.all_objects.get(pk=acme_note.pk).created_by_id is None
    assert Graph.all_objects.get(pk=beta_graph.pk).created_by_id == author.id
    assert GraphNote.all_objects.get(pk=beta_note.pk).created_by_id == author.id
    assert Graph.all_objects.get(pk=colleague_graph.pk).created_by_id == other_user.id
    assert GraphNote.all_objects.get(pk=colleague_note.pk).created_by_id == other_user.id


@pytest.mark.django_db
def test_release_clears_agent_definition_and_surface_authors_only_in_target_org(
    acme, beta, author, other_user
):
    acme_definition = AgentDefinition.objects.create(
        org=acme, name="acme-agent", created_by=author
    )
    acme_surface = Surface.objects.create(org=acme, name="acme-surface", created_by=author)
    beta_definition = AgentDefinition.objects.create(
        org=beta, name="beta-agent", created_by=author
    )
    beta_surface = Surface.objects.create(org=beta, name="beta-surface", created_by=author)
    colleague_surface = Surface.objects.create(
        org=acme, name="colleague-surface", created_by=other_user
    )

    released = AuthorshipReleaseService().release(user_id=author.id, org_id=acme.id)

    assert released == 2
    assert AgentDefinition.objects.get(pk=acme_definition.pk).created_by_id is None
    assert Surface.objects.get(pk=acme_surface.pk).created_by_id is None
    assert AgentDefinition.objects.get(pk=beta_definition.pk).created_by_id == author.id
    assert Surface.objects.get(pk=beta_surface.pk).created_by_id == author.id
    assert Surface.objects.get(pk=colleague_surface.pk).created_by_id == other_user.id


@pytest.mark.django_db
def test_release_clears_storage_file_authors_only_in_target_org(acme, beta, author, other_user):
    acme_file = StorageFile.objects.create(
        org=acme, path="docs/a.txt", name="a.txt", created_by=author
    )
    beta_file = StorageFile.objects.create(
        org=beta, path="docs/a.txt", name="a.txt", created_by=author
    )
    colleague_file = StorageFile.objects.create(
        org=acme, path="docs/b.txt", name="b.txt", created_by=other_user
    )

    released = AuthorshipReleaseService().release(user_id=author.id, org_id=acme.id)

    assert released == 1
    assert StorageFile.objects.get(pk=acme_file.pk).created_by_id is None
    assert StorageFile.objects.get(pk=beta_file.pk).created_by_id == author.id
    assert StorageFile.objects.get(pk=colleague_file.pk).created_by_id == other_user.id


@pytest.mark.django_db
def test_release_without_authored_rows_returns_zero(acme, author):
    assert AuthorshipReleaseService().release(user_id=author.id, org_id=acme.id) == 0


@pytest.mark.django_db
def test_release_rejects_author_model_without_org_lookup(monkeypatch, acme, author):
    Label.objects.create(name="kept", org=acme, created_by=author)
    monkeypatch.setattr(GraphNote, "author_org_lookup", None)

    with pytest.raises(ImproperlyConfigured, match="GraphNote"):
        AuthorshipReleaseService().release(user_id=author.id, org_id=acme.id)

    assert Label.objects.get(name="kept").created_by_id == author.id


# ---- release_outside_memberships ----


@pytest.mark.django_db
def test_release_outside_memberships_keeps_orgs_with_membership(
    acme, beta, author, other_user, role_member
):
    OrganizationUser.objects.create(user=author, org=acme, role=role_member)
    acme_graph = Graph.objects.create(name="member-flow", org=acme, created_by=author)
    beta_graph = Graph.objects.create(name="former-flow", org=beta, created_by=author)
    beta_label = Label.objects.create(name="former-label", org=beta, created_by=author)
    colleague_graph = Graph.objects.create(
        name="colleague-flow", org=beta, created_by=other_user
    )

    acme_note = GraphNote.objects.create(graph=acme_graph, content="member", created_by=author)
    beta_note = GraphNote.objects.create(graph=beta_graph, content="former", created_by=author)
    colleague_note = GraphNote.objects.create(
        graph=beta_graph, content="colleague", created_by=other_user
    )

    released = AuthorshipReleaseService().release_outside_memberships(user_id=author.id)

    assert released == 3
    assert Graph.all_objects.get(pk=acme_graph.pk).created_by_id == author.id
    assert GraphNote.all_objects.get(pk=acme_note.pk).created_by_id == author.id
    assert Graph.all_objects.get(pk=beta_graph.pk).created_by_id is None
    assert Label.objects.get(pk=beta_label.pk).created_by_id is None
    assert GraphNote.all_objects.get(pk=beta_note.pk).created_by_id is None
    assert Graph.all_objects.get(pk=colleague_graph.pk).created_by_id == other_user.id
    assert GraphNote.all_objects.get(pk=colleague_note.pk).created_by_id == other_user.id


@pytest.mark.django_db
def test_release_outside_memberships_without_memberships_releases_every_org(
    acme, beta, author
):
    acme_graph = Graph.objects.create(
        name="orphan-acme-flow",
        org=acme,
        created_by=author,
        is_soft_deleted=True,
        soft_deleted_at=timezone.now(),
    )
    beta_graph = Graph.objects.create(name="orphan-beta-flow", org=beta, created_by=author)

    released = AuthorshipReleaseService().release_outside_memberships(user_id=author.id)

    assert released == 2
    assert Graph.all_objects.get(pk=acme_graph.pk).created_by_id is None
    assert Graph.all_objects.get(pk=beta_graph.pk).created_by_id is None


@pytest.mark.django_db
def test_release_outside_memberships_leaves_rows_without_org(author):
    built_in_model = LLMModel.objects.create(
        name="authorship-built-in", llm_provider=None, org=None, created_by=author
    )

    AuthorshipReleaseService().release_outside_memberships(user_id=author.id)

    assert LLMModel.objects.get(pk=built_in_model.pk).created_by_id == author.id


@pytest.mark.django_db
def test_release_outside_memberships_rejects_author_model_without_org_lookup(
    monkeypatch, author
):
    monkeypatch.setattr(GraphNote, "author_org_lookup", None)

    with pytest.raises(ImproperlyConfigured, match="GraphNote"):
        AuthorshipReleaseService().release_outside_memberships(user_id=author.id)
