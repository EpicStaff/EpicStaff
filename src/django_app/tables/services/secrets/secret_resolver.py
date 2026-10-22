import re

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

# Third convention: `epicstaff_secret(<name>)` markers embedded in the string
# values of any header dict whose field name ends with "extra_headers"
# (`extra_headers`, `embedder_extra_headers`, `rag_llm_extra_headers`, ...).
_HEADER_FIELD_SUFFIX = "extra_headers"
_SECRET_MARKER_RE = re.compile(r"epicstaff_secret\(\s*([^)]+?)\s*\)")


def extract_secret_marker_names(headers: dict | None) -> set[str]:
    """Return the secret names `epicstaff_secret(<name>)` markers in `headers` refer to.

    Anything but a dict yields no names: rows stored before header validation existed
    may hold another JSON shape, and reading them must not fail.
    """
    if not isinstance(headers, dict):
        return set()
    names: set[str] = set()
    for value in headers.values():
        if isinstance(value, str):
            names.update(_SECRET_MARKER_RE.findall(value))
    return names


class SecretResolver:
    """Turns Secret references into plaintext at the point of use."""

    def _fetch(self, *, secret_id: int, org_id: int, context: str) -> Secret:
        """Load a Secret scoped to `org_id`, or raise."""
        secret = Secret.objects.filter(pk=secret_id, org_id=org_id).only("name", "value").first()
        if secret is None:
            raise SecretResolutionError(
                detail=self._message(context=context, secret_id=secret_id, reason="row not found")
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

    def resolve(self, *, secret_id: int | None, org_id: int, context: str = "") -> str | None:
        if secret_id is None:
            return None

        secret = self._fetch(secret_id=secret_id, org_id=org_id, context=context)
        return self._decrypt(secret=secret, context=context)

    def resolve_many(
        self, *, secret_ids: list[int | None], org_id: int, context: str = ""
    ) -> dict[int, str]:
        """Resolve several secret ids for one org in a single query."""
        unique_ids = {sid for sid in secret_ids if sid is not None}
        if not unique_ids:
            return {}

        rows = {
            secret.pk: secret
            for secret in Secret.objects.filter(pk__in=unique_ids, org_id=org_id).only(
                "id", "name", "value"
            )
        }

        resolved: dict[int, str] = {}
        for secret_id, secret in rows.items():
            try:
                resolved[secret_id] = self._decrypt(secret=secret, context=context)
            except SecretResolutionError:
                continue
        return resolved

    def resolve_named(self, *, names: list[str], org_id: int, context: str = "") -> dict[str, str]:
        """Resolve requested secret names into {name: plaintext} for one org."""
        if not names:
            return {}

        rows = {
            secret.name: secret
            for secret in Secret.objects.filter(org_id=org_id, name__in=names).only("name", "value")
        }
        return {
            name: self._decrypt(secret=rows[name], context=context)
            for name in names
            if name in rows
        }

    def resolve_payload(self, *, payload: BaseModel, org_id: int) -> BaseModel:
        """Deep-copy `payload` and fill every plaintext slot from its carrier."""
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

            if field_name.endswith(_HEADER_FIELD_SUFFIX):
                self._fill_header_markers(model=model, field_name=field_name, org_id=org_id)
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

    def resolve_header_markers(
        self, *, headers: dict[str, str] | None, org_id: int, context: str = ""
    ) -> dict[str, str] | None:
        """Return `headers` with `epicstaff_secret(<name>)` markers replaced by plaintext.

        All marker names resolve in one query against `org_id`'s secrets. Returns a
        new dict; the input is never modified, so a persisted copy keeps its markers.

        Raises:
            SecretResolutionError: A marker names a secret `org_id` does not have.
        """
        if not headers:
            return headers

        names = extract_secret_marker_names(headers)
        if not names:
            return dict(headers)

        resolved = self.resolve_named(names=sorted(names), org_id=org_id, context=context)

        missing = names - resolved.keys()
        if missing:
            raise SecretResolutionError(
                detail=(
                    f"{context}: unknown secret name(s) {sorted(missing)} "
                    f"referenced in a header marker."
                )
            )

        return {
            key: (
                _SECRET_MARKER_RE.sub(lambda m: resolved[m.group(1)], value)
                if isinstance(value, str)
                else value
            )
            for key, value in headers.items()
        }

    def _fill_header_markers(self, *, model: BaseModel, field_name: str, org_id: int) -> None:
        """Replace `epicstaff_secret(<name>)` markers in a header dict with plaintext."""
        headers = getattr(model, field_name)
        if not headers:
            return

        setattr(
            model,
            field_name,
            self.resolve_header_markers(
                headers=headers,
                org_id=org_id,
                context=f"{type(model).__name__}.{field_name}",
            ),
        )

    def _message(self, *, context: str, secret_id: int, reason: str) -> str:
        """Never interpolate the secret's value into an error message."""
        where = f" for {context}" if context else ""
        return f"Secret id={secret_id}{where} could not be resolved: {reason}."


secret_resolver = SecretResolver()
