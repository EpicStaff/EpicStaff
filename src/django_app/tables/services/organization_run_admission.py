"""A deactivated organization starts no run until it is reactivated, a superadmin's included.

Registered as a run-admission check (`tables.services.run_admission`) in `TablesConfig.ready()`.
Runs that already started are not stopped.
"""

from rbac.models import Organization
from tables.services.run_admission import RunAdmissionRefusedError, RunSubject


class OrganizationInactiveError(RunAdmissionRefusedError):
    default_code = "organization_inactive"
    default_detail = (
        "This organization is deactivated. Its runs cannot start until it is reactivated."
    )
    log_key = "organization_inactive"


class ActiveOrganizationRunCheck:
    """Refuses a run of an organization that is not active: one query, first time and again."""

    def check(self, subject: RunSubject) -> None:
        if not Organization.objects.filter(pk=subject.organization_id, is_active=True).exists():
            raise OrganizationInactiveError()

    def recheck(self, subject: RunSubject, first_look: None) -> None:
        self.check(subject)
