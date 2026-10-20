import pytest
from src.shared.retention import DataType, RetentionPolicy, RetentionRule

from rbac.governance.organization_retention import effective_retention_days_for_org
from rbac.models import OrganizationRetention

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture(autouse=True)
def retention_policy(settings):
    settings.RETENTION_POLICY = RetentionPolicy(
        rules={
            DataType.SESSIONS: RetentionRule(default_days=30, max_days=90),
            DataType.CONVERSATIONS: RetentionRule(default_days=0, max_days=None),
            DataType.AUDIT: RetentionRule(default_days=365, max_days=None),
        }
    )


@pytest.mark.django_db
def test_effective_days_for_org_without_row_is_the_default(acme):
    assert effective_retention_days_for_org(acme.id, DataType.SESSIONS) == 30
    assert effective_retention_days_for_org(acme.id, DataType.CONVERSATIONS) == 0
    assert effective_retention_days_for_org(acme.id, DataType.AUDIT) == 365
    assert not OrganizationRetention.objects.filter(org=acme).exists()


@pytest.mark.django_db
def test_effective_days_for_org_uses_the_stored_choice(acme):
    OrganizationRetention.objects.create(org=acme, conversations_days=180, sessions_days=365)

    assert effective_retention_days_for_org(acme.id, DataType.CONVERSATIONS) == 180
    assert effective_retention_days_for_org(acme.id, DataType.SESSIONS) == 90
    assert effective_retention_days_for_org(acme.id, DataType.AUDIT) == 365
