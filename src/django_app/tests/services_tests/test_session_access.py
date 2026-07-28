import pytest
from rest_framework.exceptions import NotFound

from tables.models import Graph
from tables.models.session_models import Session
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.rbac.rbac_exceptions import OrgMembershipRequiredError
from tables.services.rbac.session_access import assert_session_org_access


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="H-Org A")


@pytest.fixture
def member_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="h_member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def superadmin(db, django_user_model):
    return django_user_model.objects.create_superuser(
        email="h_super@example.com", password="StrongPass123!"
    )


def _session(org):
    graph = Graph.objects.create(name="H flow", org=org)
    return Session.objects.create(
        graph=graph, status=Session.SessionStatus.PENDING, variables={}
    )


@pytest.mark.django_db
def test_member_of_session_org_passes(member_a, org_a):
    assert_session_org_access(member_a, _session(org_a))  # no raise


@pytest.mark.django_db
def test_non_member_is_rejected(member_a):
    other_org = Organization.objects.create(name="H-Org B")
    with pytest.raises(OrgMembershipRequiredError):
        assert_session_org_access(member_a, _session(other_org))


@pytest.mark.django_db
def test_superadmin_passes(superadmin, org_a):
    assert_session_org_access(superadmin, _session(org_a))  # no raise


@pytest.mark.django_db
def test_session_without_graph_raises_not_found(member_a):
    session = Session.objects.create(
        graph=None, status=Session.SessionStatus.PENDING, variables={}
    )
    with pytest.raises(NotFound):
        assert_session_org_access(member_a, session)
