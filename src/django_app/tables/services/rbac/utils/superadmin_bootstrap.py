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

    Default-org resolution (flag-first, rename-proof):
      1. Return the org flagged `is_default=True` if one exists — the stable
         anchor that survives renames.
      2. Otherwise match by case-insensitive name on
         `settings.DEFAULT_ORGANIZATION_NAME` and self-heal the flag (covers
         orgs created before the flag existed).
      3. Otherwise create the row with the env-configured name, flagged.
      - Race-safety: the create runs in a nested savepoint; if it races a
        parallel insert and IntegrityError fires (name or single-default
        constraint), refetch and use the winner.
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
        # 1. Stable anchor — survives rename.
        org = Organization.objects.filter(is_default=True).first()
        if org is not None:
            return org, False

        # 2. First-ever creation only: nothing flagged yet, match by configured
        #    name and self-heal the flag.
        org_name = settings.DEFAULT_ORGANIZATION_NAME
        org = Organization.objects.filter(name__iexact=org_name).first()
        if org is not None:
            if not org.is_default:
                org.is_default = True
                org.save(update_fields=["is_default"])
            return org, False

        # 3. Truly empty system: create it, flagged. The nested savepoint keeps
        #    a failed insert from poisoning the caller's outer atomic block, so
        #    the refetch below is actually reachable on a lost race.
        try:
            with transaction.atomic():
                return (
                    Organization.objects.create(name=org_name, is_default=True),
                    True,
                )
        except IntegrityError:
            # Race lost — another transaction created the row between our
            # filter and create. The DB-level constraints are ground truth;
            # refetch and use the winner.
            winner = (
                Organization.objects.filter(is_default=True).first()
                or Organization.objects.filter(name__iexact=org_name).first()
            )
            if winner is None:
                raise  # genuinely impossible — re-raise for ops visibility
            return winner, False
