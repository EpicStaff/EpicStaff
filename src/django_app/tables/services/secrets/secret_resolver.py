from pydantic import BaseModel

from tables.models import Secret
from tables.services.secrets.encryption import secret_encryption
from tables.services.secrets.exceptions import (
    SecretDecryptionError,
    SecretResolutionError,
)

_SECRET_ID_SUFFIX = "_secret_id"

# The reserved pair, beside the <field>_secret_id convention: the names a node's
# code asks for resolve into a {name: plaintext} dict. No collision —
# "secret_names".endswith("_secret_id") is False.
_NAMED_NAMES_FIELD = "secret_names"
_NAMED_VALUES_FIELD = "secrets"


class SecretResolver:
    """Turns Secret references into plaintext at the point of use.

    Django is the only service holding SECRET_KEY, so this is the only place in
    the platform where a stored credential can be opened. Resolution happens as
    late as possible.
    """

    def _fetch(self, *, secret_id: int, org_id: int, context: str) -> Secret:
        """Load a Secret scoped to `org_id`, or raise.

        The org filter is what makes a foreign secret indistinguishable from a
        missing one: same query, same exception, same message.
        """
        secret = (
            Secret.objects.filter(pk=secret_id, org_id=org_id)
            .only("name", "value")
            .first()
        )
        if secret is None:
            raise SecretResolutionError(
                detail=self._message(
                    context=context, secret_id=secret_id, reason="row not found"
                )
            )
        return secret

    def _decrypt(self, *, secret: Secret, context: str) -> str:
        try:
            return secret_encryption.decrypt(encryptedtext=secret.value)
        except SecretDecryptionError as exc:
            raise SecretResolutionError(
                detail=self._message(
                    context=context, secret_id=secret.pk, reason="value not decryptable"
                )
            ) from exc

    def resolve(
        self, *, secret_id: int | None, org_id: int, context: str = ""
    ) -> str | None:
        if secret_id is None:
            return None

        secret = self._fetch(secret_id=secret_id, org_id=org_id, context=context)
        return self._decrypt(secret=secret, context=context)

    def resolve_named(
        self, *, names: list[str], org_id: int, context: str = ""
    ) -> dict[str, str]:
        """Resolve requested secret names into {name: plaintext} for one org.

        Keyed by name because that is what the user typed in the Secrets tab and
        what get_secret() asks for; Secret has UniqueConstraint(org, name), so
        the name is a stable per-org key. `org_id` scopes the lookup — with names
        there is no id to leak or to dangle across installations.

        A name with no matching Secret is omitted, not an error: the name comes
        from a string literal in user code, so a typo must not stop the whole
        flow from starting. The sandbox raises SecretNotAvailableError at the
        get_secret() call and lists what WAS injected, which is both the most
        informative place to fail and still fail-closed — no credential is
        exposed either way.

        A row that exists but will not decrypt still raises: that is an
        infrastructure fault, not a user typo.
        """
        if not names:
            return {}

        rows = {
            secret.name: secret
            for secret in Secret.objects.filter(org_id=org_id, name__in=names).only(
                "name", "value"
            )
        }
        return {
            name: self._decrypt(secret=rows[name], context=context)
            for name in names
            if name in rows
        }

    def resolve_payload(self, *, payload: BaseModel, org_id: int) -> BaseModel:
        """Deep-copy `payload` and fill every plaintext slot from its carrier.

        The copy is the point: callers hand the *original* to the database and
        the returned copy to Redis, so a resolved value cannot reach a resource
        row by accident.
        """
        resolved = payload.model_copy(deep=True)
        self._fill(node=resolved, org_id=org_id)
        return resolved

    def _fill(self, *, node, org_id: int) -> None:
        if isinstance(node, BaseModel):
            self._fill_model(model=node, org_id=org_id)
        elif isinstance(node, (list, tuple)):
            for item in node:
                self._fill(node=item, org_id=org_id)
        elif isinstance(node, dict):
            for value in node.values():
                self._fill(node=value, org_id=org_id)

    def _fill_model(self, *, model: BaseModel, org_id: int) -> None:
        model_cls = type(model)
        for field_name in model_cls.model_fields:
            if field_name == _NAMED_NAMES_FIELD:
                self._fill_named(model=model, org_id=org_id)
                continue

            if not field_name.endswith(_SECRET_ID_SUFFIX):
                self._fill(node=getattr(model, field_name), org_id=org_id)
                continue

            target = field_name[: -len(_SECRET_ID_SUFFIX)]
            if target not in model_cls.model_fields:
                raise SecretResolutionError(
                    detail=(
                        f"{model_cls.__name__}.{field_name} has no paired "
                        f"'{target}' field; the <field>_secret_id convention is "
                        f"broken."
                    )
                )

            secret_id = getattr(model, field_name)
            if secret_id is None:
                continue
            setattr(
                model,
                target,
                self.resolve(
                    secret_id=secret_id,
                    org_id=org_id,
                    context=f"{model_cls.__name__}.{target}",
                ),
            )

    def _fill_named(self, *, model: BaseModel, org_id: int) -> None:
        model_cls = type(model)
        if _NAMED_VALUES_FIELD not in model_cls.model_fields:
            raise SecretResolutionError(
                detail=(
                    f"{model_cls.__name__}.{_NAMED_NAMES_FIELD} has no paired "
                    f"'{_NAMED_VALUES_FIELD}' field; the reserved "
                    f"secret_names/secrets pair is broken."
                )
            )
        setattr(
            model,
            _NAMED_VALUES_FIELD,
            self.resolve_named(
                names=getattr(model, _NAMED_NAMES_FIELD),
                org_id=org_id,
                context=f"{model_cls.__name__}.{_NAMED_VALUES_FIELD}",
            ),
        )

    def _message(self, *, context: str, secret_id: int, reason: str) -> str:
        """Never interpolate the secret's value into an error message."""
        where = f" for {context}" if context else ""
        return f"Secret id={secret_id}{where} could not be resolved: {reason}."


secret_resolver = SecretResolver()
