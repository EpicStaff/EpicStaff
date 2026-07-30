from tables.models import Secret
from tables.services.secrets.encryption import secret_encryption


class SecretService:
    """Create/update Secret rows."""

    def auto_name(self, *, org, model_name: str, field_name: str) -> str:
        """Name for a Secret created implicitly behind a config's FK: no pk in
        the name, numbered suffix only if this org already has one for this
        exact model+field (e.g. "llmconfig-api-key", then "llmconfig-api-key-2").
        """
        base_name = f"{model_name}-{field_name.replace('_', '-')}"
        existing_names = set(
            Secret.objects.filter(org=org, name__startswith=base_name).values_list(
                "name", flat=True
            )
        )
        if base_name not in existing_names:
            return base_name
        n = 2
        while f"{base_name}-{n}" in existing_names:
            n += 1
        return f"{base_name}-{n}"

    def create_for_field(self, *, text: str, org, instance, field_name: str) -> Secret:
        """Create a Secret to sit behind `instance.<field_name>`, auto-naming it."""
        return self.create(
            text=text,
            org=org,
            name=self.auto_name(
                org=org,
                model_name=instance.__class__.__name__.lower(),
                field_name=field_name,
            ),
        )

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
