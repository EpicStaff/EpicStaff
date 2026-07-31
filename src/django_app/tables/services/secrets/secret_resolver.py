from pydantic import BaseModel

from tables.models import Secret
from tables.services.secrets.encryption import secret_encryption
from tables.services.secrets.exceptions import (
    SecretDecryptionError,
    SecretResolutionError,
)

_SECRET_ID_SUFFIX = "_secret_id"


class SecretResolver:
    """Turns Secret references into plaintext at the point of use.

    Django is the only service holding SECRET_KEY, so this is the only place in
    the platform where a stored credential can be opened. Resolution happens as
    late as possible.
    """

    def resolve(self, *, secret_id: int | None, context: str = "") -> str | None:
        if secret_id is None:
            return None

        secret = Secret.objects.filter(pk=secret_id).only("value").first()
        if secret is None:
            raise SecretResolutionError(
                detail=self._message(
                    context=context, secret_id=secret_id, reason="row not found"
                )
            )
        try:
            return secret_encryption.decrypt(encryptedtext=secret.value)
        except SecretDecryptionError as exc:
            raise SecretResolutionError(
                detail=self._message(
                    context=context, secret_id=secret_id, reason="value not decryptable"
                )
            ) from exc

    def resolve_payload(self, *, payload: BaseModel) -> BaseModel:
        """Deep-copy `payload` and fill every plaintext slot from its carrier.

        The copy is the point: callers hand the *original* to the database and
        the returned copy to Redis, so a resolved value cannot reach a resource
        row by accident.
        """
        resolved = payload.model_copy(deep=True)
        self._fill(node=resolved)
        return resolved

    def _fill(self, *, node) -> None:
        if isinstance(node, BaseModel):
            self._fill_model(model=node)
        elif isinstance(node, (list, tuple)):
            for item in node:
                self._fill(node=item)
        elif isinstance(node, dict):
            for value in node.values():
                self._fill(node=value)

    def _fill_model(self, *, model: BaseModel) -> None:
        model_cls = type(model)
        for field_name in model_cls.model_fields:
            if not field_name.endswith(_SECRET_ID_SUFFIX):
                self._fill(node=getattr(model, field_name))
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
                    context=f"{model_cls.__name__}.{target}",
                ),
            )

    def _message(self, *, context: str, secret_id: int, reason: str) -> str:
        """Never interpolate the secret's value into an error message."""
        where = f" for {context}" if context else ""
        return f"Secret id={secret_id}{where} could not be resolved: {reason}."


secret_resolver = SecretResolver()
