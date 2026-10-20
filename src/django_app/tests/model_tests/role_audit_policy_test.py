import pytest
from django.db import IntegrityError, transaction

from rbac.access.audit_history import AUDIT_HISTORY_DAYS_MAX, sync_audit_policy
from rbac.models import Role, RoleAuditPolicy


@pytest.fixture
def role(db):
    return Role.objects.create(name="Policy probe", is_built_in=False)


@pytest.mark.django_db
@pytest.mark.parametrize("history_days", [0, AUDIT_HISTORY_DAYS_MAX + 1])
def test_database_rejects_a_limit_outside_the_range(role, history_days):
    """Unlimited is stored as no row, never as 0."""
    with pytest.raises(IntegrityError), transaction.atomic():
        RoleAuditPolicy.objects.create(role=role, history_days=history_days)


@pytest.mark.django_db
@pytest.mark.parametrize("history_days", [1, AUDIT_HISTORY_DAYS_MAX])
def test_database_accepts_the_range_bounds(role, history_days):
    RoleAuditPolicy.objects.create(role=role, history_days=history_days)

    assert RoleAuditPolicy.objects.get(role=role).history_days == history_days


@pytest.mark.django_db
def test_sync_creates_changes_and_deletes_the_row(role):
    sync_audit_policy(role, 30)
    assert RoleAuditPolicy.objects.get(role=role).history_days == 30

    sync_audit_policy(role, 7)
    assert RoleAuditPolicy.objects.get(role=role).history_days == 7

    sync_audit_policy(role, 0)
    assert not RoleAuditPolicy.objects.filter(role=role).exists()


@pytest.mark.django_db
def test_policy_is_deleted_with_its_role(role):
    RoleAuditPolicy.objects.create(role=role, history_days=30)

    role.delete()

    assert not RoleAuditPolicy.objects.exists()
