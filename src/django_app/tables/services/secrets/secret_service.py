from tables.models import Secret
from tables.services.secrets.encryption import secret_encryption
from tables.validators.secret_name_validator import validate_secret_name


class SecretService:
    """Create/update Secret rows."""

    def create(self, *, text: str, system: bool = False, **fields) -> Secret:
        """Encrypt `text` and save it as a new Secret.

        Validates the name itself as a guard: callers that skip a serializer
        (quickstart, system storage credentials) build their names on the
        server, so a forbidden name here is a programming error.
        """
        secret = Secret(system=system, **fields)
        validate_secret_name(secret.name)
        secret_encryption.encrypt(text=text).write_to(secret)
        secret.save()
        return secret


secret_service = SecretService()
