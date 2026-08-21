from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction

from tables.models.rbac_models import (
    Organization,
    OrganizationUser,
)
from tables.services.rbac.rbac_exceptions import SetupAlreadyCompletedError
from tables.services.rbac.utils.bootstrap_lock import acquire_bootstrap_lock
from tables.services.rbac.utils.superadmin_bootstrap import SuperadminBootstrap


@dataclass
class SetupResult:
    user: "User"
    organization: Organization
    membership: OrganizationUser
    default_org_created: bool = False


class FirstSetupService:
    """
    Bootstrap the very first superadmin and their default organization.

    - `is_setup_required()` returns True if no User row exists.
    - `setup(...)` is atomic and idempotent-checked: it refuses if any user
      already exists ("When this setup is completed once, it never appears
      again" — re-opens only if all users are removed).

    The organization name always comes from `settings.DEFAULT_ORGANIZATION_NAME`
    (driven by the `DEFAULT_ORGANIZATION_NAME` env var, with a sane fallback).
    It is not taken from the HTTP request body.

    `org_name` overrides `settings.DEFAULT_ORGANIZATION_NAME` when a new
    organization is created, and is ignored when one already exists.
    """

    _bootstrap = SuperadminBootstrap()

    def is_setup_required(self) -> bool:
        return not get_user_model().objects.exists()

    @transaction.atomic
    def setup(
        self, *, email: str, password: str, org_name: str | None = None
    ) -> SetupResult:
        # Before the existence check, not after: the guard is only sound if
        # no other writer can insert a user between the check and our own
        # insert.
        acquire_bootstrap_lock()

        if get_user_model().objects.exists():
            raise SetupAlreadyCompletedError()

        result = self._bootstrap.provision(
            email=email,
            password=password,
            org_name=org_name,
        )

        return SetupResult(
            user=result.user,
            organization=result.organization,
            membership=result.membership,
            default_org_created=result.default_org_created,
        )
