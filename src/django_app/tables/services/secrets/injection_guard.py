from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from tables.services.secrets.exceptions import SecretInjectionDeniedError
from tables.services.secrets.policies import SECRET_POLICIES, RowWrite, SecretPolicy
from tables.services.secrets.reference_guard import (
    SecretActor,
    SecretReferenceGuard,
    secret_reference_guard,
)

#: Every config whose policy records a binding approver, by model. A config type whose
#: policy records none (ElevenLabs, Gemini, the realtime model configs) declares no
#: destination: it can only reach its provider's fixed endpoint.
_INJECTED_CONFIGS: dict[type, SecretPolicy] = {
    policy.approval_model: policy for policy in SECRET_POLICIES if policy.records_binding_approval
}

# Decisions already made in the current payload build, keyed by (model, pk) and by
# (user, org); None outside `batch()`, so nothing outlives one build.
_decisions: ContextVar[dict | None] = ContextVar("secret_injection_decisions", default=None)


class SecretInjectionGuard:
    """Refuses to put a config's secret into a payload bound for an unvouched custom destination.

    The write-time guard (SecretReferenceGuard) makes pointing a secret-bearing config
    at a custom destination require secrets:USE. This is the same rule at injection
    time, judged on the saved row: a config whose secret goes anywhere but the trusted
    catalog is injected only if the user who approved its secret binding
    (`secret_binding_approved_by`, see SecretBindingApprovedModel) still holds
    secrets:USE in the config's org. It fails closed -- no approver (never approved, a
    deleted user), an approver who left the org, or one who lost USE is denied.
    """

    def __init__(self, guard: SecretReferenceGuard | None = None):
        self._guard = guard or secret_reference_guard

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Reuse decisions across one payload build, so each config and each approver is looked up once."""
        token = _decisions.set({})
        try:
            yield
        finally:
            _decisions.reset(token)

    def assert_injection_permitted(self, config) -> None:
        """Raise SecretInjectionDeniedError unless `config` may ship its secret where it routes it.

        Free for a catalog destination or a config that carries no secret; otherwise the
        approver row and one permission resolution, each once per `batch()`.

        Raises:
            SecretInjectionDeniedError: The secret goes to a custom destination and the
                config's approver is unknown or no longer holds secrets:USE.
        """
        if config is None:
            return
        policy = _INJECTED_CONFIGS.get(type(config))
        if policy is None:
            return
        if self._remembered(
            ("config", type(config), config.pk), lambda: self._may_inject(policy, config)
        ):
            return
        raise SecretInjectionDeniedError(
            f'{policy.approval_label} "{config.custom_name}" sends its secret to a custom destination, but '
            'no one who holds the "Use" permission on Secrets has approved that. Ask an '
            "organization admin who holds that permission to re-save it."
        )

    def injectable_api_key_secret_id(self, config) -> int | None:
        """The config's API-key secret id for a payload, once `assert_injection_permitted` passes."""
        if config is None:
            return None
        self.assert_injection_permitted(config)
        return config.api_key_secret_id

    def _may_inject(self, policy: SecretPolicy, config) -> bool:
        if not policy.sends_secret_to_custom_destination(RowWrite.of_persisted_row(config)):
            return True
        approver_id = config.secret_binding_approved_by_id
        if approver_id is None:
            return False
        return self._remembered(
            ("approver", approver_id, config.org_id),
            lambda: self._guard.may_use(
                SecretActor(user=config.secret_binding_approved_by, org_id=config.org_id)
            ),
        )

    @staticmethod
    def _remembered(key, decide) -> bool:
        decisions = _decisions.get()
        if decisions is None:
            return decide()
        if key not in decisions:
            decisions[key] = decide()
        return decisions[key]


secret_injection_guard = SecretInjectionGuard()
