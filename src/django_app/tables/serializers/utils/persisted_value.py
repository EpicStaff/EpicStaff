class PersistedValueMixin:
    """Lets a serializer say what its persisted row holds at a field's source.

    The one place both SecretReferenceGuardMixin (to tell a change from a resend) and
    KeptLinkPrimaryKeyRelatedField (to accept an unchanged link to a binned row) read
    the current value. Override `persisted_value` where it is not an attribute of
    `self.instance`: a nested serializer, whose instance is None, reads through its
    parent's row; a value one relation away reads through that relation.
    """

    def persisted_value(self, source: str):
        """The value the persisted row holds at `source`, or None on create."""
        return getattr(self.instance, source, None)
