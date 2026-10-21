from tables.services.secrets.reference_guard import secret_destination_guard

# The fields that decide where a model sends requests, beyond the provider's vendor host.
LLM_MODEL_ENDPOINT_FIELDS = ("base_url", "deployment_id")
EMBEDDING_MODEL_ENDPOINT_FIELDS = ("base_url", "deployment")


class SecretDestinationGuardMixin:
    """Keeps a pinned-org principal from setting where a model sends a config's key.

    For the models a secret-holding config points at; `secret_destination_fields` names the
    sources that decide the endpoint (a URL, a deployment).
    """

    secret_destination_fields: tuple[str, ...] = ()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        secret_destination_guard.assert_may_change_endpoints(
            serializer=self, attrs=attrs, fields=self.secret_destination_fields
        )
        return attrs
