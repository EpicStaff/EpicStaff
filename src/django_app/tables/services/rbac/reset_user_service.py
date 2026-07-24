from django.contrib.auth import get_user_model
from django.db import transaction

from tables.services.rbac.utils.superadmin_bootstrap import SuperadminBootstrap


class ResetUserService:
    """
    Wipes all Users, then provisions a fresh superadmin with a default-org
    membership via SuperadminBootstrap. The Organizations table is preserved
    across the wipe — the bootstrap re-uses the existing default org if
    present, or creates one if not.

    User-owned API keys cascade-delete with their owning users; the system
    API key (owned by no user) survives the wipe untouched. No new key is
    created here — personal keys come only from POST /api/profile/api-keys/.

    Returns the new user. The view layer wraps it in the response payload.
    """

    _bootstrap = SuperadminBootstrap()

    @transaction.atomic
    def reset(self, *, email: str, password: str):
        UserModel = get_user_model()
        UserModel.objects.all().delete()  # user keys cascade; system key survives

        result = self._bootstrap.provision(email=email, password=password)
        return result.user
