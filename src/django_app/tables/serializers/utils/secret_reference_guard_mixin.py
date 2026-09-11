from tables.services.secrets.reference_guard import secret_reference_guard


class SecretReferenceGuardMixin:
    """Requires secrets:USE to change which secrets a resource references."""

    secret_reference_fields: tuple[str, ...] = ()
    parent_attribute: str | None = None

    def get_secret_reference_fields(self) -> tuple[str, ...]:
        """The guarded fields for this serializer; override on a subclass to diverge on one request path."""
        # Read through this method rather than the attribute directly so a per-path
        # subclass -- a `*BulkSerializer`, or an endpoint-specific variant -- can differ
        # from the class its siblings share, without every other user of that class
        # moving with it. 
        return self.secret_reference_fields

    def validate(self, attrs):
        """Run the parent validation, then gate any change to a guarded secret field."""
        attrs = super().validate(attrs)
        secret_reference_guard.assert_unchanged_or_permitted(
            serializer=self, attrs=attrs, fields=self.get_secret_reference_fields()
        )
        return attrs
