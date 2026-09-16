import pytest
from django.db.models import Q

from tables.models.rbac_models import Role
from tables.models.rbac_models.rbac_enums import ResourceType
from tables.services.rbac.cross_org_service import CrossOrgResourceService
from tables.services.rbac.rbac_exceptions import RoleNotFoundError

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


class _ScopedService(CrossOrgResourceService):
    rbac_resource_type = ResourceType.ROLES
    not_found_exception = RoleNotFoundError
    delegated_scope_q = Q(name__startswith="Visible")


@pytest.fixture
def service():
    return _ScopedService()


@pytest.mark.django_db
def test_delegated_caller_gets_the_extra_restriction(service, admin_acme, acme):
    Role.objects.create(name="Visible-one", org=acme, is_built_in=False)
    Role.objects.create(name="Hidden-one", org=acme, is_built_in=False)

    names = set(
        service.apply_org_scope(
            actor=admin_acme, org_ids=None, base_qs=Role.objects.all()
        ).values_list("name", flat=True)
    )

    assert names == {"Visible-one"}


@pytest.mark.django_db
def test_superadmin_is_exempt_from_the_extra_restriction(service, superadmin, acme):
    Role.objects.create(name="Visible-one", org=acme, is_built_in=False)
    Role.objects.create(name="Hidden-one", org=acme, is_built_in=False)

    names = set(
        service.apply_org_scope(
            actor=superadmin, org_ids=None, base_qs=Role.objects.all()
        ).values_list("name", flat=True)
    )

    assert {"Visible-one", "Hidden-one"} <= names


@pytest.mark.django_db
def test_superadmin_stays_exempt_when_filtering_by_org_ids(service, superadmin, acme):
    Role.objects.create(name="Visible-one", org=acme, is_built_in=False)
    Role.objects.create(name="Hidden-one", org=acme, is_built_in=False)

    names = set(
        service.apply_org_scope(
            actor=superadmin, org_ids=[acme.id], base_qs=Role.objects.all()
        ).values_list("name", flat=True)
    )

    assert names == {"Visible-one", "Hidden-one"}
