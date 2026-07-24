from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction

from tables.models.rbac_models import (
    Organization,
    OrganizationUser,
)
from tables.services.rbac.rbac_exceptions import SetupAlreadyCompletedError
from tables.services.rbac.utils.superadmin_bootstrap import SuperadminBootstrap


@dataclass
class SetupResult:
    user: "User"
    organization: Organization
    membership: OrganizationUser


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
    """

    _bootstrap = SuperadminBootstrap()

    def is_setup_required(self) -> bool:
        return not get_user_model().objects.exists()

    @transaction.atomic
    def setup(self, *, email: str, password: str) -> SetupResult:
        if get_user_model().objects.exists():
            raise SetupAlreadyCompletedError()

        result = self._bootstrap.provision(
            email=email,
            password=password,
        )

        return SetupResult(
            user=result.user,
            organization=result.organization,
            membership=result.membership,
        )
