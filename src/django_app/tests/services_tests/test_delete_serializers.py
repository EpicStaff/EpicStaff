from dataclasses import asdict

from tables.serializers.delete_serializers import (
    OrganizationDeleteReportSerializer,
    UserDeleteReportSerializer,
)
from tables.services.rbac.organization_management_service import OrganizationDeleteReport
from tables.services.rbac.user_management_service import UserDeleteReport

# The tests proving these serializers accept the REAL delete_user/
# delete_organization output (not just the hand-written fixtures below) live
# next to those services, where the actor/target fixtures they need already
# exist: tests/services_tests/test_user_management_service.py and
# tests/services_tests/test_organization_management_service.py.


def test_user_delete_report_serializer_accepts_a_user_report():
    report = UserDeleteReport(
        user_id=42,
        affected_resources={"memberships": 1, "api_keys": 3},
    )

    serializer = UserDeleteReportSerializer(data=asdict(report))

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {
        "user_id": 42,
        "affected_resources": {"memberships": 1, "api_keys": 3},
    }


def test_organization_delete_report_serializer_accepts_an_organization_report():
    report = OrganizationDeleteReport(
        organization_id=7,
        affected_resources={"flow": 3, "storage_files": 219},
    )

    serializer = OrganizationDeleteReportSerializer(data=asdict(report))

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {
        "organization_id": 7,
        "affected_resources": {"flow": 3, "storage_files": 219},
    }
