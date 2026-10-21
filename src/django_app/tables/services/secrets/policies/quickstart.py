from tables.services.secrets.policies.base import SecretPolicy

QUICKSTART_SECRET_POLICY = SecretPolicy(reference_fields=("api_key_secret_id",))
