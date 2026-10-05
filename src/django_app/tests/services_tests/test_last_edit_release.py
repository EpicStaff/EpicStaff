from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from agents.models import AgentDefinition
from rbac.authorship import record_last_edit
from rbac.governance.authorship import AuthorshipReleaseService
from rbac.models import OrganizationUser, ResourceLastEdit
from tables.models import Graph, GraphNote, StorageFile

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

EDITED_AT = timezone.now() - timedelta(days=1)


@pytest.fixture
def editor(db, django_user_model):
    return django_user_model.objects.create_user(
        email="editor-release@example.com", password="StrongPass123!"
    )


@pytest.fixture
def colleague(db, django_user_model):
    return django_user_model.objects.create_user(
        email="colleague-release@example.com", password="StrongPass123!"
    )


def _last_edit_of(instance) -> ResourceLastEdit:
    return ResourceLastEdit.objects.get(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    )


@pytest.mark.django_db
def test_release_clears_editor_only_in_target_org_and_keeps_time(acme, beta, editor, colleague):
    # Authored by the colleague, so the editor's edits do not claim them and only last
    # edits are released.
    acme_graph = Graph.objects.create(name="acme-edited", org=acme, created_by=colleague)
    deleted_graph = Graph.objects.create(
        name="acme-deleted-edited",
        org=acme,
        is_soft_deleted=True,
        soft_deleted_at=timezone.now(),
        created_by=colleague,
    )
    acme_note = GraphNote.objects.create(graph=acme_graph, content="acme", created_by=colleague)
    acme_definition = AgentDefinition.objects.create(
        org=acme, name="acme-agent", created_by=colleague
    )
    acme_file = StorageFile.objects.create(
        org=acme, path="a.txt", name="a.txt", created_by=colleague
    )
    beta_graph = Graph.objects.create(name="beta-edited", org=beta, created_by=colleague)
    beta_note = GraphNote.objects.create(graph=beta_graph, content="beta", created_by=colleague)
    colleague_note = GraphNote.objects.create(graph=acme_graph, content="colleague")
    for instance in (acme_graph, deleted_graph, acme_note, acme_definition, acme_file):
        record_last_edit(instance, editor, edited_at=EDITED_AT)
    for instance in (beta_graph, beta_note):
        record_last_edit(instance, editor, edited_at=EDITED_AT)
    record_last_edit(colleague_note, colleague, edited_at=EDITED_AT)

    released = AuthorshipReleaseService().release(user_id=editor.id, org_id=acme.id)

    assert released == 5
    for instance in (acme_graph, deleted_graph, acme_note, acme_definition, acme_file):
        last_edit = _last_edit_of(instance)
        assert last_edit.edited_by_id is None, type(instance).__name__
        assert last_edit.edited_at == EDITED_AT
    assert _last_edit_of(beta_graph).edited_by_id == editor.id
    assert _last_edit_of(beta_note).edited_by_id == editor.id
    assert _last_edit_of(colleague_note).edited_by_id == colleague.id


@pytest.mark.django_db
def test_release_counts_authorship_and_last_edits_together(acme, editor):
    graph = Graph.objects.create(name="authored-and-edited", org=acme, created_by=editor)
    record_last_edit(graph, editor, edited_at=EDITED_AT)

    released = AuthorshipReleaseService().release(user_id=editor.id, org_id=acme.id)

    assert released == 2
    assert Graph.objects.get(pk=graph.pk).created_by_id is None
    assert _last_edit_of(graph).edited_by_id is None


@pytest.mark.django_db
def test_release_outside_memberships_keeps_editor_in_member_orgs(
    acme, beta, editor, colleague, role_member
):
    OrganizationUser.objects.create(user=editor, org=acme, role=role_member)
    acme_note = GraphNote.objects.create(
        graph=Graph.objects.create(name="member-flow", org=acme), content="kept"
    )
    # Authored by the colleague, so the editor's edit does not claim it and only its last
    # edit is released.
    beta_note = GraphNote.objects.create(
        graph=Graph.objects.create(name="non-member-flow", org=beta),
        content="released",
        created_by=colleague,
    )
    record_last_edit(acme_note, editor, edited_at=EDITED_AT)
    record_last_edit(beta_note, editor, edited_at=EDITED_AT)

    released = AuthorshipReleaseService().release_outside_memberships(user_id=editor.id)

    assert released == 1
    assert _last_edit_of(acme_note).edited_by_id == editor.id
    beta_last_edit = _last_edit_of(beta_note)
    assert beta_last_edit.edited_by_id is None
    assert beta_last_edit.edited_at == EDITED_AT


@pytest.mark.django_db
def test_member_removal_clears_last_editor_in_that_org(
    acme, beta, admin_acme, member_only, client_as
):
    acme_graph = Graph.objects.create(name="removal-flow", org=acme)
    beta_graph = Graph.objects.create(name="removal-beta-flow", org=beta)
    record_last_edit(acme_graph, member_only, edited_at=EDITED_AT)
    record_last_edit(beta_graph, member_only, edited_at=EDITED_AT)
    membership = OrganizationUser.objects.get(user=member_only, org=acme)

    response = client_as(admin_acme).delete(f"/api/admin/memberships/{membership.id}/")

    assert response.status_code == 204, response.content
    acme_last_edit = _last_edit_of(acme_graph)
    assert acme_last_edit.edited_by_id is None
    assert acme_last_edit.edited_at == EDITED_AT
    assert _last_edit_of(beta_graph).edited_by_id == member_only.id
