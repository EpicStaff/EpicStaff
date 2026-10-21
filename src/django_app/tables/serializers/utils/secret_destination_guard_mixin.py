from tables.services.secrets.reference_guard import secret_destination_guard


class SecretDestinationGuardMixin:
    """Lets a pinned-org principal change where a model sends a config's key only on its own rows.

    For the models a secret-holding config points at; `secret_destination_fields` names the
    sources that decide the endpoint (a URL, the provider).
    """

    secret_destination_fields: tuple[str, ...] = ()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        secret_destination_guard.assert_may_change_endpoints(
            serializer=self, attrs=attrs, fields=self.secret_destination_fields
        )
        return attrs
