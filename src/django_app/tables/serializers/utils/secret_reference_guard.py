from tables.services.secrets.reference_guard import secret_reference_guard


class SecretReferenceGuardMixin:
    """Requires secrets:USE to change which secrets a resource references."""

    secret_reference_fields: tuple[str, ...] = ()
    parent_attribute: str | None = None

    def validate(self, attrs):
        """Run the parent validation, then gate any change to a guarded secret field."""
        attrs = super().validate(attrs)
        secret_reference_guard.assert_unchanged_or_permitted(
            serializer=self, attrs=attrs, fields=self.secret_reference_fields
        )
        return attrs
