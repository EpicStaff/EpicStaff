from tables.services.secrets.reference_guard import secret_reference_guard

#: The destination of a config whose model is a built-in catalog row, or that has none.
#: The catalog is superadmin-managed, so moving between its rows is not gated.
CATALOG_DESTINATION = "catalog"


def model_destination(model) -> object:
    """Where a provider config sends its request, judged by the model it uses.

    Routing depends on more than the model's base_url -- litellm also routes on the
    model name, provider, api_version and deployment -- so the destination is the
    model's identity: a custom model is its own destination (its pk), every built-in
    catalog model shares one trusted destination.
    """
    if model is None or (not model.is_custom and model.org_id is None):
        return CATALOG_DESTINATION
    return model.pk


class SecretReferenceGuardMixin:
    """Requires secrets:USE to change which secrets a resource references, or where it sends them.

    Declare what applies to the serializer:

    - `secret_reference_fields`: FK/M2M fields that point at a Secret.
    - `secret_header_fields`: JSON header fields whose `epicstaff_secret(<name>)`
      markers resolve to org secrets by name.
    - `get_secret_destination` + `carries_secret_reference`: override both when the
      row decides where a secret-bearing request goes -- its own base URL, every
      routing field of a model row (`writable_values_after_save`), or an FK to a model
      (`model_destination`).
    """

    secret_reference_fields: tuple[str, ...] = ()
    secret_header_fields: tuple[str, ...] = ()
    parent_attribute: str | None = None

    def get_secret_reference_fields(self) -> tuple[str, ...]:
        """The guarded fields for this serializer; override on a subclass to diverge on one request path."""
        # Read through this method rather than the attribute directly so a per-path
        # subclass -- a `*BulkSerializer`, or an endpoint-specific variant -- can differ
        # from the class its siblings share, without every other user of that class
        # moving with it.
        return self.secret_reference_fields

    def get_secret_header_fields(self) -> tuple[str, ...]:
        """The guarded header fields for this serializer; overridable per request path like the FK fields."""
        return self.secret_header_fields

    def get_secret_destination(self, attrs) -> dict:
        """Where a request carrying this row's secrets goes once `attrs` is applied, as {field name: value}.

        Called with `{}` for the persisted destination. The default declares none, so
        the destination check never fires.
        """
        return {}

    def carries_secret_reference(self, attrs) -> bool:
        """Whether a secret travels to this row's destination once `attrs` is applied."""
        return False

    def value_after_save(self, attrs, source, *, persisted_attribute=None):
        """The value `source` holds once `attrs` is saved: the incoming one, else the persisted one.

        `persisted_attribute` reads a different attribute off the instance -- pass
        `<fk>_id` to test an FK for presence without loading the related row.
        """
        if source in attrs:
            return attrs[source]
        return getattr(self.instance, persisted_attribute or source, None)

    def writable_values_after_save(self, attrs, *, exclude) -> dict:
        """{field name: value once `attrs` is saved} for every writable field not in `exclude`.

        Related rows compare by pk. Built for a model row's destination: listing the
        fields that do NOT route (rather than those that do) keeps a field added later
        gated until someone decides it is cosmetic.
        """
        values = {}
        for name, field in self.fields.items():
            if field.read_only or name in exclude:
                continue
            value = self.value_after_save(attrs, field.source)
            # Blank and null route the same, and the frontend sends null for an emptied
            # field; treating them as different would deny a save that changes nothing.
            values[name] = None if value == "" else getattr(value, "pk", value)
        return values

    def validate(self, attrs):
        """Run the parent validation, then gate any change to a guarded secret reference or destination."""
        attrs = super().validate(attrs)
        secret_reference_guard.assert_unchanged_or_permitted(
            serializer=self, attrs=attrs, fields=self.get_secret_reference_fields()
        )
        secret_reference_guard.assert_header_markers_unchanged_or_permitted(
            serializer=self, attrs=attrs, fields=self.get_secret_header_fields()
        )
        secret_reference_guard.assert_destination_unchanged_or_permitted(
            serializer=self, attrs=attrs
        )
        return attrs
