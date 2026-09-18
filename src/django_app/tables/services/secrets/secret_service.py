from tables.models import Secret
from tables.services.secrets.encryption import secret_encryption


class SecretService:
    """Create/update Secret rows."""

    def create(self, *, text: str, **fields) -> Secret:
        secret = Secret(**fields)
        secret_encryption.encrypt(text=text).write_to(secret)
        secret.save()
        return secret


secret_service = SecretService()
