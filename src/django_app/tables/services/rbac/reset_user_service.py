from django.contrib.auth import get_user_model
from django.db import transaction


from tables.models.rbac_models import ApiKey


class ResetUserService:
    """
    Wipes all Users and ApiKeys, then recreates a superadmin + a default
    realtime API key. Does NOT touch Organizations (D3 option A).

    Superadmin gets no automatic org membership — is_superadmin bypasses all
    permission checks, and we don't want to silently rewrite existing org
    ownership. Callers who need a membership can add one manually.
    """

    REALTIME_KEY_NAME = "realtime-default"

    @transaction.atomic
    def reset(self, *, email: str, password: str) -> tuple:
        user_model = get_user_model()

        user_model.objects.all().delete()
        ApiKey.objects.all().delete()

        user = user_model.objects.create_superuser(email=email, password=password)

        raw_key = ApiKey.generate_raw_key()
        key = ApiKey(name=self.REALTIME_KEY_NAME, created_by=user)
        key.set_key(raw_key)
        key.save()

        return user, raw_key
