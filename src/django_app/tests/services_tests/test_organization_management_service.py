"""Sequential (non-concurrent) service-layer tests for
OrganizationManagementService.deactivate_organization.

These tests cover the four distinct branch paths through the method that are
not exercised by the concurrency suite in
test_organization_management_service_concurrency.py:

  1. Active org deactivated successfully when others remain.
  2. Last active org raises LastActiveOrganizationError.
  3. Already-inactive org is a silent no-op (does not raise even when it is the
     only inactive org and the active set has exactly one member).
  4. Nonexistent org_id raises OrganizationNotFoundError.

Plain @pytest.mark.django_db is sufficient -- no cross-connection visibility
or FOR UPDATE serialization is under test here.

What is NOT duplicated here:
  - Concurrent deactivation race (two threads, last two active orgs) --
    covered in test_organization_management_service_concurrency.py.
  - Both-succeed case with three active orgs under concurrency -- same file.
"""

import pytest

from rbac.models import Organization
from tables.services.rbac.organization_management_service import (
    OrganizationManagementService,
)
from tables.services.rbac.rbac_exceptions import (
    LastActiveOrganizationError,
    OrganizationNotFoundError,
)


@pytest.fixture
def service():
    return OrganizationManagementService()


@pytest.mark.django_db
def test_deactivate_active_org_succeeds_when_others_remain(service):
    """Deactivating one of two active organizations succeeds.

    The if-branch fires (org_id in orgs_map) and len(orgs_map) == 2 > 1, so
    the guard allows the deactivation. The returned org has is_active=False
    and the sibling org remains active.
    """
    Organization.objects.filter(is_active=True).update(is_active=False)

    org_a = Organization.objects.create(name="SeqDeactivateA", is_active=True)
    org_b = Organization.objects.create(name="SeqDeactivateB", is_active=True)

    result = service.deactivate_organization(org_a.pk)

    assert result.pk == org_a.pk
    assert result.is_active is False

    org_a.refresh_from_db()
    assert org_a.is_active is False

    org_b.refresh_from_db()
    assert org_b.is_active is True


@pytest.mark.django_db
def test_deactivate_last_active_org_raises(service):
    """Deactivating the sole active organization raises LastActiveOrganizationError.

    The if-branch fires (org_id in orgs_map) and len(orgs_map) == 1, which
    trips the guard immediately.
    """
    Organization.objects.filter(is_active=True).update(is_active=False)

    org = Organization.objects.create(name="SeqLastActive", is_active=True)

    with pytest.raises(LastActiveOrganizationError):
        service.deactivate_organization(org.pk)

    org.refresh_from_db()
    assert org.is_active is True


@pytest.mark.django_db
def test_deactivate_already_inactive_org_is_no_op(service):
    """Deactivating an already-inactive org is a silent no-op.

    The else-branch fires (_get_locked_org) because the target is not in
    orgs_map (inactive orgs are excluded from the active-set query). The
    subsequent `if target.is_active` guard is False, so the save is skipped.
    No LastActiveOrganizationError is raised even though the system has exactly
    one active org -- B is already inactive, so the invariant is not threatened.
    """
    Organization.objects.filter(is_active=True).update(is_active=False)

    Organization.objects.create(name="SeqIdempotentGuard", is_active=True)
    org_b = Organization.objects.create(name="SeqIdempotentTarget", is_active=False)

    result = service.deactivate_organization(org_b.pk)

    assert result.pk == org_b.pk
    assert result.is_active is False

    org_b.refresh_from_db()
    assert org_b.is_active is False


@pytest.mark.django_db
def test_deactivate_nonexistent_org_raises_not_found(service):
    """Deactivating an org_id that matches no row raises OrganizationNotFoundError.

    The else-branch fires (_get_locked_org) and translates DoesNotExist into
    the project-standard 404 envelope.
    """
    with pytest.raises(OrganizationNotFoundError):
        service.deactivate_organization(999_999)
