import pytest
from src.shared.retention import DataType, RetentionPolicy, RetentionRule

from rbac.governance.organization_retention import effective_retention_days_for_org
from rbac.models import OrganizationConfig

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture(autouse=True)
def retention_policy(settings):
    settings.RETENTION_POLICY = RetentionPolicy(
        rules={
            DataType.SESSIONS: RetentionRule(default_days=30, max_days=90),
            DataType.CONVERSATIONS: RetentionRule(default_days=0, max_days=None),
            DataType.AUDIT: RetentionRule(default_days=365, max_days=None, min_days=90),
        }
    )


@pytest.mark.django_db
def test_effective_days_for_org_without_config_row_is_the_default(acme):
    assert effective_retention_days_for_org(acme.id, DataType.SESSIONS) == 30
    assert effective_retention_days_for_org(acme.id, DataType.CONVERSATIONS) == 0
    assert effective_retention_days_for_org(acme.id, DataType.AUDIT) == 365
    assert not OrganizationConfig.objects.filter(org=acme).exists()


@pytest.mark.django_db
def test_effective_days_for_org_with_config_but_no_choice_is_the_default(acme):
    OrganizationConfig.objects.create(org=acme)

    assert effective_retention_days_for_org(acme.id, DataType.SESSIONS) == 30
    assert effective_retention_days_for_org(acme.id, DataType.AUDIT) == 365


@pytest.mark.django_db
def test_effective_days_for_org_uses_the_stored_choice_within_cap_and_floor(acme):
    OrganizationConfig.objects.create(
        org=acme,
        retention_conversations_days=180,
        retention_sessions_days=365,
        retention_audit_days=30,
    )

    assert effective_retention_days_for_org(acme.id, DataType.CONVERSATIONS) == 180
    assert effective_retention_days_for_org(acme.id, DataType.SESSIONS) == 90
    assert effective_retention_days_for_org(acme.id, DataType.AUDIT) == 90


@pytest.mark.django_db
def test_effective_days_for_org_ignores_the_audit_visibility_setting(acme):
    OrganizationConfig.objects.create(org=acme, audit_retention_days=30)

    assert effective_retention_days_for_org(acme.id, DataType.AUDIT) == 365
