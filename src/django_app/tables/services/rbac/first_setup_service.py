from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from loguru import logger

from tables.models.rbac_models import (
    ApiKey,
    Organization,
    OrganizationUser,
    Role,
)
from tables.services.rbac.rbac_exceptions import (
    DefaultOrganizationConflictError,
    SetupAlreadyCompletedError,
)


@dataclass
class SetupResult:
    user: "User"
    organization: Organization
    membership: OrganizationUser
    api_key: ApiKey


class FirstSetupService:
    """
    Bootstrap the very first superadmin and their default organization.

    - `is_setup_required()` returns True if no User row exists.
    - `setup(...)` is atomic and idempotent-checked: it refuses if any user
      already exists ("When this setup is completed once, it never
      appears again" — re-opens only if all users are removed).

    The organization name always comes from `settings.DEFAULT_ORGANIZATION_NAME`
    (driven by the `DEFAULT_ORGANIZATION_NAME` env var, with a sane fallback).
    It is not taken from the HTTP request body.
    """

    ORG_ADMIN_ROLE_NAME = "Org Admin"
    DEFAULT_API_KEY_NAME = "epicstaff-apikey"

    def is_setup_required(self) -> bool:
        return not get_user_model().objects.exists()

    @transaction.atomic
    def setup(self, *, email: str, password: str) -> SetupResult:
        user_model = get_user_model()

        if user_model.objects.exists():
            raise SetupAlreadyCompletedError()

        org_name = settings.DEFAULT_ORGANIZATION_NAME

        user = user_model.objects.create_superuser(
            email=email,
            password=password,
        )

        try:
            organization = Organization.objects.create(name=org_name)
        except IntegrityError as exc:
            # Org row survived a prior user wipe (User delete cascades
            # OrganizationUser but not Organization). Surface as a clean 409.
            raise DefaultOrganizationConflictError() from exc

        # Superadmin bypasses permission checks globally via `is_superadmin`,
        # but per Story 1 spec they also get the Org Admin role in the default
        # org so the UI sees a consistent membership record.
        org_admin_role = Role.objects.get(
            name=self.ORG_ADMIN_ROLE_NAME, is_built_in=True, org__isnull=True
        )
        membership = OrganizationUser.objects.create(
            user=user, org=organization, role=org_admin_role
        )

        raw_key = ApiKey.generate_raw_key()
        api_key = ApiKey(name=self.DEFAULT_API_KEY_NAME, created_by=user)
        api_key.set_key(raw_key)
        api_key.save()

        # Raw key is surfaced only here — it's not returned from the HTTP
        # endpoint. Ops / dev reads it from the django_app container logs.
        logger.info(
            "First-setup API key generated for user={email} name={name} "
            "prefix={prefix} raw_key={raw_key}",
            email=user.email,
            name=api_key.name,
            prefix=api_key.prefix,
            raw_key=raw_key,
        )

        return SetupResult(
            user=user,
            organization=organization,
            membership=membership,
            api_key=api_key,
        )
