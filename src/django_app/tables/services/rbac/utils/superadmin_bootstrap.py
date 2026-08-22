from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from loguru import logger

from tables.models.rbac_models import (
    Organization,
    OrganizationUser,
    Role,
)
from tables.models.rbac_models.rbac_enums import BuiltInRole

# Last-resort organization name. settings.DEFAULT_ORGANIZATION_NAME already
# coalesces an empty env var, but the fallback is repeated here at the point
# of use so a blank value from any source can never name an organization "".
DEFAULT_ORG_NAME_FALLBACK = "Organization"


@dataclass
class SuperadminBootstrapResult:
    user: "User"
    organization: Organization
    membership: OrganizationUser
    default_org_created: bool


class SuperadminBootstrap:
    """Provisions a superadmin + default-org membership.

    Used by both FirstSetupService (initial bootstrap) and ResetUserService
    (destructive reset, Bug 1 fix). The caller is responsible for the
    surrounding `transaction.atomic()` and any pre-checks ("no users exist
    yet" for first-setup; the wipe for reset-user).

    Default-org resolution (flag-first, rename-proof):
      1. Return the org flagged `is_default=True` if one exists — the stable
         anchor that survives renames.
      2. Otherwise match by case-insensitive name on the configured name —
         `settings.DEFAULT_ORGANIZATION_NAME` (never `org_name`, which only
         ever names a brand-new organization) — and self-heal the flag
         (covers orgs created before the flag existed).
      3. Otherwise create the row with the resolved name (the `org_name`
         argument if given, else the configured name), flagged.
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
        org_name: str | None = None,
    ) -> SuperadminBootstrapResult:
        UserModel = get_user_model()
        user = UserModel.objects.create_superuser(email=email, password=password)

        organization, default_org_created = self._get_or_create_default_org(
            org_name=org_name
        )

        role = Role.objects.get(
            name=self.SUPERADMIN_ROLE_NAME,
            is_built_in=True,
            org__isnull=True,
        )
        membership = OrganizationUser.objects.create(
            user=user, org=organization, role=role
        )

        # API keys are never provisioned here — user keys come only from
        # POST /api/profile/api-keys/, the system key only from
        # seed_system_api_key.
        logger.info(
            "SuperadminBootstrap provisioned email={email} org={org} role={role}",
            email=user.email,
            org=organization.name,
            role=role.name,
        )

        return SuperadminBootstrapResult(
            user=user,
            organization=organization,
            membership=membership,
            default_org_created=default_org_created,
        )

    @staticmethod
    def _get_or_create_default_org(
        org_name: str | None = None,
    ) -> tuple[Organization, bool]:
        # The configured name identifies a pre-existing organization to adopt;
        # org_name only ever names a brand-new one. Keeping them separate stops
        # an explicit --org-name from orphaning a legacy unflagged row that
        # other code still resolves by the configured name.
        configured_name = (
            settings.DEFAULT_ORGANIZATION_NAME or DEFAULT_ORG_NAME_FALLBACK
        ).strip() or DEFAULT_ORG_NAME_FALLBACK
        resolved_name = (org_name or configured_name).strip() or configured_name

        # 1. Stable anchor — survives rename.
        org = Organization.objects.filter(is_default=True).first()
        if org is not None:
            return org, False

        # 2. First-ever creation only: nothing flagged yet, match by the
        #    configured name only (org_name never adopts an existing row)
        #    and self-heal the flag.
        org = Organization.objects.filter(name__iexact=configured_name).first()
        if org is not None:
            if not org.is_default:
                org.is_default = True
                org.save(update_fields=["is_default"])
            return org, False

        # 3. Truly empty system: create it with the resolved name, flagged.
        #    The nested savepoint keeps a failed insert from poisoning the
        #    caller's outer atomic block, so the refetch below is actually
        #    reachable on a lost race.
        try:
            with transaction.atomic():
                return (
                    Organization.objects.create(name=resolved_name, is_default=True),
                    True,
                )
        except IntegrityError:
            # Race lost — another transaction created the row between our
            # filter and create. The DB-level constraints are ground truth;
            # refetch and use the winner.
            winner = (
                Organization.objects.filter(is_default=True).first()
                or Organization.objects.filter(name__iexact=resolved_name).first()
                or Organization.objects.filter(name__iexact=configured_name).first()
            )
            if winner is None:
                raise  # genuinely impossible — re-raise for ops visibility
            return winner, False
