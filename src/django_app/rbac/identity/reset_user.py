from django.contrib.auth import get_user_model
from django.db import transaction
from utils.logger import logger

from rbac.governance.authorship import SnapshotAuthorshipScrubService
from rbac.identity.bootstrap_lock import acquire_bootstrap_lock
from rbac.identity.superadmin_bootstrap import SuperadminBootstrap


class ResetUserService:
    """
    Wipes all Users, then provisions a fresh superadmin with a default-org
    membership via SuperadminBootstrap. The Organizations table is preserved
    across the wipe — the bootstrap re-uses the existing default org if
    present, or creates one if not.

    Flows and their versions survive too, so every user recorded in a version
    snapshot is cleared first: restoring a version replays the recorded ids,
    which would otherwise point at no user.

    User-owned API keys cascade-delete with their owning users; the system
    API key (owned by no user) survives the wipe untouched. No new key is
    created here — personal keys come only from POST /api/profile/api-keys/.

    Returns the new user. The view layer wraps it in the response payload.
    Writes one audit log line naming the actor (None means the CLI), how many
    users were deleted and the new superadmin.
    """

    _bootstrap = SuperadminBootstrap()

    @transaction.atomic
    def reset(self, *, email: str, password: str, display_name: str | None = None, actor=None):
        acquire_bootstrap_lock()

        SnapshotAuthorshipScrubService().scrub_every_user()
        UserModel = get_user_model()  # noqa: N806
        users_deleted = UserModel.objects.count()
        UserModel.objects.all().delete()  # user keys cascade; system key survives

        result = self._bootstrap.provision(
            email=email, password=password, display_name=display_name
        )
        logger.info(
            "ResetUserService.reset actor={actor} users_deleted={deleted} new_superadmin={new}",
            actor=getattr(actor, "email", "cli"),
            deleted=users_deleted,
            new=result.user.email,
        )
        return result.user
