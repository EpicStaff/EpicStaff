from functools import cache

from rbac.scoping.fields import resolve_active_org_id
from rest_framework import serializers
from tables.serializers.utils.persisted_value import PersistedValueMixin
from tables.services.secrets.exceptions import SecretUseDeniedError
from tables.services.secrets.policies import RowWrite, SecretPolicy
from tables.services.secrets.reference_guard import SecretActor, secret_reference_guard


class SecretReferenceGuardMixin(PersistedValueMixin):
    """Requires secrets:USE to change which secrets a resource references, or where it sends them.

    Set `secret_policy` to the entity's SecretPolicy; it decides what is guarded. A
    per-path subclass (a `*BulkSerializer`, an endpoint-specific variant) that must
    guard differently sets its own policy, leaving its siblings unchanged.
    """

    secret_policy: SecretPolicy

    def validate(self, attrs):
        """Run the parent validation, then let SecretReferenceGuard gate the write.

        The approval attrs it returns (who approved the row's secret binding) join
        `attrs`, so save() stamps them.
        """
        attrs = super().validate(attrs)
        write = RowWrite(
            instance=self.instance,
            attrs=attrs,
            writable_fields={
                name: field.source for name, field in self.fields.items() if not field.read_only
            },
            persisted_value=self.persisted_value,
        )
        try:
            approval = secret_reference_guard.authorize_write(
                policy=self.secret_policy, write=write, resolve_actor=cache(self._secret_actor)
            )
        except SecretUseDeniedError as denial:
            raise serializers.ValidationError({denial.field_name: denial.message}) from denial
        return {**attrs, **approval}

    def _secret_actor(self) -> SecretActor | None:
        request = self.context.get("request")
        if request is None:
            return None
        return SecretActor(user=request.user, org_id=resolve_active_org_id(request))
