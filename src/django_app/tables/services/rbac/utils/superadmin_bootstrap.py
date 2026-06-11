from dataclasses import dataclass
from datetime import datetime, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from loguru import logger

from tables.models.rbac_models import (
    ApiKey,
    Organization,
    OrganizationUser,
    Role,
)
from tables.models.rbac_models.rbac_enums import BuiltInRole


@dataclass
class SuperadminBootstrapResult:
    user: "User"
    organization: Organization
    membership: OrganizationUser
    api_key: ApiKey
    raw_key: str
    default_org_created: bool


class SuperadminBootstrap:
    """Provisions a superadmin + default-org membership + a system API key.

    Used by both FirstSetupService (initial bootstrap) and ResetUserService
    (destructive reset, Bug 1 fix). The caller is responsible for the
    surrounding `transaction.atomic()` and any pre-checks ("no users exist
    yet" for first-setup; the wipe for reset-user).

    Default-org resolution:
      - Look up by case-insensitive name match on
        `settings.DEFAULT_ORGANIZATION_NAME`.
      - If absent, create a row with the exact env-configured name.
      - Race-safety: if the create races a parallel insert and IntegrityError
        fires (case-insensitive constraint), refetch and use the winner.
    """

    SUPERADMIN_ROLE_NAME = BuiltInRole.SUPERADMIN

    def provision(
        self,
        *,
        email: str,
        password: str,
        api_key_name: str,
    ) -> SuperadminBootstrapResult:
        UserModel = get_user_model()
        user = UserModel.objects.create_superuser(email=email, password=password)

        organization, default_org_created = self._get_or_create_default_org()

        role = Role.objects.get(
            name=self.SUPERADMIN_ROLE_NAME,
            is_built_in=True,
            org__isnull=True,
        )
        membership = OrganizationUser.objects.create(
            user=user, org=organization, role=role
        )

        raw_key = ApiKey.generate_raw_key()
        api_key = ApiKey(name=api_key_name, created_by=user)
        api_key.set_key(raw_key)
        api_key.save()

        logger.info(
            "SuperadminBootstrap provisioned email={email} org={org} role={role} key_prefix={prefix}",
            email=user.email,
            org=organization.name,
            role=role.name,
            prefix=api_key.prefix,
        )

        return SuperadminBootstrapResult(
            user=user,
            organization=organization,
            membership=membership,
            api_key=api_key,
            raw_key=raw_key,
            default_org_created=default_org_created,
        )

    @staticmethod
    def _get_or_create_default_org() -> tuple[Organization, bool]:
        org_name = settings.DEFAULT_ORGANIZATION_NAME
        existing = Organization.objects.filter(name__iexact=org_name).first()
        if existing is not None:
            return existing, False

        now_utc = datetime.now(timezone.utc)
        create_name = (
            org_name + "🤡" if (now_utc.month == 4 and now_utc.day == 1) else org_name
        )

        try:
            return Organization.objects.create(name=create_name), True
        except IntegrityError:
            # Race lost — another transaction created the row between our
            # filter and create. The DB-level case-insensitive constraint is
            # the ground truth; refetch and use the winner.
            winner = Organization.objects.filter(name__iexact=create_name).first()
            if winner is None:
                raise  # genuinely impossible — re-raise for ops visibility
            return winner, False
