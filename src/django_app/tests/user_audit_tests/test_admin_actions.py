"""Superadmin actions on users and organizations, recorded through the cross-org admin API.

Presentation tests: each goes through its endpoint. The request has no checked org, so the
middleware's fallback never records these; the governance services do. Only the object
store an organization delete sweeps is replaced.
"""

import pytest
from rest_framework import status

from rbac.models import Organization, OrganizationUser
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

USERS_URL = "/api/admin/users/"
ORGANIZATIONS_URL = "/api/admin/organizations/"


@pytest.fixture
def member_in_two_orgs(member_only, beta, role_member):
    OrganizationUser.objects.create(user=member_only, org=beta, role=role_member)
    return member_only


@pytest.fixture
def superadmin_client(client_as, superadmin):
    return client_as(superadmin)


@pytest.fixture(autouse=True)
def _stub_org_storage(mocker):
    # Object storage is an external boundary: an organization gets its own storage user on
    # create and reactivate, loses it on deactivate, and a delete removes its prefix.
    backend = mocker.MagicMock()
    backend.list_all_objects.return_value = []
    mocker.patch("tables.services.organization_deletion.get_storage_backend", return_value=backend)
    mocker.patch("rbac.governance.organizations.org_storage_provisioning_service")


def _send(client, method, url, capture, body=None):
    with capture(execute=True):
        response = getattr(client, method)(url, body, format="json")
    assert response.status_code < status.HTTP_400_BAD_REQUEST, response.content
    return response


def _records(events) -> list[tuple]:
    return sorted(
        (event.action, event.org_id, event.target_type, event.target_id, event.target_name)
        for event in events
    )


@pytest.mark.parametrize(
    "path, expected_action",
    [
        ("grant-superadmin", "superadmin_granted"),
        ("deactivate", "deactivated"),
    ],
)
def test_a_superadmin_change_to_a_user_is_recorded_in_each_of_their_orgs(
    path,
    expected_action,
    superadmin_client,
    superadmin,
    member_in_two_orgs,
    acme,
    beta,
    sent_events,
    django_capture_on_commit_callbacks,
):
    _send(
        superadmin_client,
        "post",
        f"{USERS_URL}{member_in_two_orgs.id}/{path}/",
        django_capture_on_commit_callbacks,
    )

    target = ("user", str(member_in_two_orgs.id), member_in_two_orgs.email)
    assert _records(sent_events) == sorted(
        [(expected_action, acme.id, *target), (expected_action, beta.id, *target)]
    )
    assert {event.actor_email for event in sent_events} == {superadmin.email}


def test_reactivating_a_user_records_reactivated_and_a_repeat_records_nothing(
    superadmin_client, member_only, acme, sent_events, django_capture_on_commit_callbacks
):
    member_only.is_active = False
    member_only.save(update_fields=["is_active"])
    url = f"{USERS_URL}{member_only.id}/reactivate/"

    _send(superadmin_client, "post", url, django_capture_on_commit_callbacks)
    _send(superadmin_client, "post", url, django_capture_on_commit_callbacks)

    assert _records(sent_events) == [
        ("reactivated", acme.id, "user", str(member_only.id), member_only.email)
    ]


def test_revoking_superadmin_is_recorded_in_the_orgs_the_user_belongs_to(
    superadmin_client, django_user_model, acme, role_member, sent_events,
    django_capture_on_commit_callbacks,
):
    # A grant purges every membership, so only a membership added since gets the record.
    second_superadmin = django_user_model.objects.create_user(
        email="second-superadmin@example.com", password="StrongPass123!", is_superadmin=True
    )
    OrganizationUser.objects.create(user=second_superadmin, org=acme, role=role_member)

    _send(
        superadmin_client,
        "post",
        f"{USERS_URL}{second_superadmin.id}/revoke-superadmin/",
        django_capture_on_commit_callbacks,
    )

    assert _records(sent_events) == [
        ("superadmin_revoked", acme.id, "user", str(second_superadmin.id), second_superadmin.email)
    ]


def test_deleting_a_user_is_recorded_in_each_org_they_belonged_to_by_their_email(
    superadmin_client,
    member_in_two_orgs,
    acme,
    beta,
    sent_events,
    django_capture_on_commit_callbacks,
):
    user_id, email = member_in_two_orgs.id, member_in_two_orgs.email

    _send(
        superadmin_client,
        "delete",
        f"{USERS_URL}{user_id}/",
        django_capture_on_commit_callbacks,
        {"verification_phrase": f"delete-{email}"},
    )

    assert not OrganizationUser.objects.filter(user_id=user_id).exists()
    assert _records(sent_events) == sorted(
        [
            ("deleted", acme.id, "user", str(user_id), email),
            ("deleted", beta.id, "user", str(user_id), email),
        ]
    )


def test_creating_an_organization_is_recorded_in_it(
    superadmin_client, superadmin, sent_events, django_capture_on_commit_callbacks
):
    response = _send(
        superadmin_client,
        "post",
        ORGANIZATIONS_URL,
        django_capture_on_commit_callbacks,
        {"name": "Gamma"},
    )

    org = Organization.objects.get(pk=response.data["id"])
    assert _records(sent_events) == [("created", org.id, "organization", str(org.id), "Gamma")]
    assert sent_events[0].actor_email == superadmin.email


def test_deactivating_and_reactivating_an_organization_are_recorded_in_it(
    superadmin_client, acme, beta, sent_events, django_capture_on_commit_callbacks
):
    for path in ("deactivate", "reactivate"):
        _send(
            superadmin_client,
            "post",
            f"{ORGANIZATIONS_URL}{beta.id}/{path}/",
            django_capture_on_commit_callbacks,
        )

    assert [
        (event.action, event.org_id, event.target_id, event.target_name) for event in sent_events
    ] == [
        ("deactivated", beta.id, str(beta.id), beta.name),
        ("reactivated", beta.id, str(beta.id), beta.name),
    ]


def test_deleting_an_organization_is_recorded_in_its_own_trail_by_name(
    superadmin_client, acme, beta, sent_events, django_capture_on_commit_callbacks
):
    beta_id, beta_name = beta.id, beta.name

    _send(
        superadmin_client,
        "delete",
        f"{ORGANIZATIONS_URL}{beta_id}/",
        django_capture_on_commit_callbacks,
        {"verification_phrase": f"delete-{beta_name}"},
    )

    assert not Organization.objects.filter(pk=beta_id).exists()
    assert _records(sent_events) == [
        ("deleted", beta_id, "organization", str(beta_id), beta_name)
    ]


def test_a_refused_organization_delete_records_nothing(
    superadmin_client, acme, beta, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = superadmin_client.delete(
            f"{ORGANIZATIONS_URL}{beta.id}/", {"verification_phrase": "wrong"}, format="json"
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert sent_events == []
