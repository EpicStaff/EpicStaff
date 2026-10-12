import pytest
from django.urls import reverse
from rest_framework import status

from agents.models import AgentDefinition
from agents.models.surface_models import Surface
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.user_summary_helpers import expected_user_summary

AGENT_DEFINITION = "agentdefinition"
SURFACE = "surface"
MODEL_BY_BASENAME = {AGENT_DEFINITION: AgentDefinition, SURFACE: Surface}


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _list_url(basename: str) -> str:
    return reverse(f"{basename}-list")


def _detail_url(basename: str, pk: int) -> str:
    return reverse(f"{basename}-detail", args=[pk])


def _author_id(basename: str, pk: int) -> int | None:
    model = MODEL_BY_BASENAME[basename]
    return model.objects.values_list("created_by_id", flat=True).get(pk=pk)


# Developer's Surface API takes PATCH only; an agent accepts both.
EDIT_METHODS = [(AGENT_DEFINITION, "put"), (AGENT_DEFINITION, "patch"), (SURFACE, "patch")]


def _edit_body(basename: str, name: str, **extra) -> dict:
    """An agent edits its instructions through `instruction_list`; a surface through `instructions`."""
    if basename == AGENT_DEFINITION:
        content = {"instruction_list": [{"name": "Instruction_1.md", "content": "edited"}]}
    else:
        content = {"instructions": "edited"}
    return {"name": name, **content, **extra}


def _create_row(basename: str, org, name: str, author=None):
    return MODEL_BY_BASENAME[basename].objects.create(org=org, name=name, created_by=author)


# ---- create ----


@pytest.mark.django_db
@pytest.mark.parametrize("basename", [AGENT_DEFINITION, SURFACE])
def test_create_stamps_active_org_and_acting_user(
    basename, acme_client, admin_acme, member_only, acme, beta
):
    response = acme_client.post(
        _list_url(basename),
        {"name": f"authored-{basename}", "org": beta.id, "created_by": member_only.id},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    row = MODEL_BY_BASENAME[basename].objects.get(name=f"authored-{basename}")
    assert row.org_id == acme.id
    assert row.created_by_id == admin_acme.id


@pytest.mark.django_db
@pytest.mark.parametrize("basename", [AGENT_DEFINITION, SURFACE])
def test_read_response_exposes_org_and_author(basename, acme_client, member_only, acme):
    member_only.display_name = "Member Only"
    member_only.save(update_fields=["display_name"])
    row = _create_row(basename, acme, f"read-{basename}", author=member_only)

    response = acme_client.get(_detail_url(basename, row.pk))

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["org"] == acme.id
    assert response.data["created_by"] == {
        "id": member_only.id,
        "display_name": "Member Only",
        "avatar_url": None,
    }
    assert "organization" not in response.data


# ---- update: never sets or replaces the author ----


@pytest.mark.django_db
@pytest.mark.parametrize(("basename", "method"), EDIT_METHODS)
def test_update_of_unauthored_row_leaves_it_unauthored(basename, method, acme_client, acme):
    row = _create_row(basename, acme, f"ownerless-{basename}")

    response = getattr(acme_client, method)(
        _detail_url(basename, row.pk),
        _edit_body(basename, f"edited-{basename}"),
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["name"] == f"edited-{basename}"
    assert _author_id(basename, row.pk) is None
    assert response.data["created_by"] is None


@pytest.mark.django_db
@pytest.mark.parametrize(("basename", "method"), EDIT_METHODS)
def test_update_of_authored_row_keeps_author_even_when_body_names_one(
    basename, method, acme_client, admin_acme, member_only, acme
):
    row = _create_row(basename, acme, f"authored-{basename}", author=member_only)

    response = getattr(acme_client, method)(
        _detail_url(basename, row.pk),
        _edit_body(basename, f"renamed-{basename}", created_by=admin_acme.id),
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(basename, row.pk) == member_only.id


# ---- cross-org ----


@pytest.mark.django_db
@pytest.mark.parametrize("basename", [AGENT_DEFINITION, SURFACE])
def test_cross_org_get_returns_404(basename, acme_client, beta):
    row = _create_row(basename, beta, f"beta-{basename}")

    response = acme_client.get(_detail_url(basename, row.pk))

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
@pytest.mark.parametrize("basename", [AGENT_DEFINITION, SURFACE])
def test_cross_org_patch_returns_404_and_leaves_row_unauthored(basename, acme_client, beta):
    row = _create_row(basename, beta, f"beta-{basename}")

    response = acme_client.patch(
        _detail_url(basename, row.pk), {"instructions": "hijacked"}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    row.refresh_from_db()
    assert row.instructions == ""
    assert row.created_by_id is None


@pytest.mark.django_db
@pytest.mark.parametrize("basename", [AGENT_DEFINITION, SURFACE])
def test_cross_org_delete_returns_404_and_keeps_row(basename, acme_client, beta):
    row = _create_row(basename, beta, f"beta-{basename}")

    response = acme_client.delete(_detail_url(basename, row.pk))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert MODEL_BY_BASENAME[basename].objects.filter(pk=row.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("basename", [AGENT_DEFINITION, SURFACE])
def test_list_shows_only_active_org_rows(basename, acme_client, acme, beta):
    _create_row(basename, acme, f"acme-{basename}")
    _create_row(basename, beta, f"beta-{basename}")

    response = acme_client.get(_list_url(basename))

    assert response.status_code == status.HTTP_200_OK, response.content
    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    assert {row["name"] for row in rows} == {f"acme-{basename}"}
