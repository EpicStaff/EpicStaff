from tables.models import Secret
from tables.services.secrets.encryption import secret_encryption


class SecretService:
    """Create/update Secret rows."""

    def create(self, *, text: str, **fields) -> Secret:
        secret = Secret(**fields)
        secret_encryption.encrypt(text=text).write_to(secret)
        secret.save()
        return secret

    def update(self, instance: Secret, *, text: str | None = None, **fields) -> Secret:
        for attr, val in fields.items():
            setattr(instance, attr, val)
        if text is not None:
            secret_encryption.encrypt(text=text).write_to(instance)
        instance.save()
        return instance


secret_service = SecretService()
