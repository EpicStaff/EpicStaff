"""Check a config's `parameters` and `connection` against the model catalog."""

import functools
from collections import defaultdict
from datetime import UTC, datetime

from jsonschema import Draft202012Validator
from tables.exceptions import ConfigValidationError
from tables.models import Secret
from tables.services.secrets.secret_resolver import extract_secret_marker_names

from ai_models.domain.schemas import ConfigSchemaFactory
from ai_models.domain.specs import ModelKind
from ai_models.domain.value_types import ValueTypeRegistry
from ai_models.repository import CatalogRepository

_UNKNOWN_KEY = "Not supported for this provider and model."
_REQUIRED = "This field is required."
_NOT_AN_OBJECT = "Must be an object."
# Stands in for the validator's own message on a secret field, which quotes the value.
_SECRET_FIELD = "Must be an epicstaff_secret(<name>) marker naming a secret."
_MARKER_OUTSIDE_SECRET_FIELD = "Secret markers are only allowed in secret fields."


@functools.cache
def schema_factory(repository: CatalogRepository) -> ConfigSchemaFactory:
    """Return the one schema factory of `repository`, so its schema memo is shared process-wide."""
    return ConfigSchemaFactory(repository, ValueTypeRegistry())


class ConfigValidationService:
    """The one rule every write path follows for a config's settings and connection.

    `validate` is strict, for writes. `review_reasons`, `allowed_parameters` and
    `drop_unsupported` are lenient, for stored configs a catalog update made stale:
    those keep running and only show "needs review". An import is fitted like a stale
    config (`drop_unsupported`, `drop_undeclared_connection_fields`) and is strict only
    on what no config may store (`validate_import`).
    """

    def __init__(self, repository: CatalogRepository | None = None) -> None:
        self._repository = repository or CatalogRepository.default()
        self._schemas = schema_factory(self._repository)

    def validate(
        self,
        kind: ModelKind,
        provider: str,
        model_name: str,
        parameters: dict,
        connection: dict,
        org_id: int,
        *,
        stored_connection: dict | None = None,
    ) -> None:
        """Reject unknown keys, values the catalog does not allow and unknown secret markers.

        An `epicstaff_secret(<name>)` marker is allowed only in a secret connection field
        and must name a secret of `org_id`; another organization's secret fails exactly
        like a missing one.

        Args:
            stored_connection: The connection an update keeping the provider replaces;
                None for a create or a provider change. A required connection field it
                lacks and `connection` still lacks is not asked for, and a field the
                provider does not declare that `connection` resends unchanged is not
                refused: such a config, often one the data migration could not fill or
                left a field on, shows "needs review" instead.

        Raises:
            ConfigValidationError: Its detail is `{"parameters": {name: [message]},
                "connection": {name: [message]}}`, holding only the parts that have
                errors; its `errors` list each message under the dotted field path. The
                value of a secret connection field, or of one the provider does not
                declare, is left out of `errors`.
        """
        parameter_errors = _errors(
            self._schemas.parameters_schema(kind, provider, model_name), parameters
        )
        connection_errors = self._connection_errors(provider, connection, org_id)
        if stored_connection is not None and isinstance(connection_errors, dict):
            declared = self._schemas.connection_schema(provider)["properties"]
            connection_errors = {
                name: messages
                for name, messages in connection_errors.items()
                # A field absent from both can only carry the "required" error.
                if (name in connection or name in stored_connection)
                # An undeclared field resent unchanged is one no form shows (a catalog
                # update or the data migration left it): the config shows "needs review".
                and not (
                    name not in declared
                    and name in stored_connection
                    and connection.get(name) == stored_connection[name]
                )
            }
        self._raise_errors(provider, parameters, parameter_errors, connection, connection_errors)

    def validate_import(
        self, provider: str, parameters: object, connection: object, org_id: int
    ) -> None:
        """Refuse what no imported config may store, whatever export version it came from.

        Both parts must be objects, and each connection field present follows the rules of
        `validate`, secret markers included. Required connection fields are not asked for,
        since export files older than these fields cannot hold them, and setting values are
        not checked: an import keeps them as they are, and a config they no longer fit
        shows "needs review". Run it after `drop_unsupported` and
        `drop_undeclared_connection_fields`, or an undeclared field is refused.

        Raises:
            ConfigValidationError: Shaped as in `validate`.
        """
        parameter_errors = {} if isinstance(parameters, dict) else [_NOT_AN_OBJECT]
        connection_errors = self._connection_errors(provider, connection, org_id)
        if isinstance(connection_errors, dict):
            connection_errors = {
                name: messages for name, messages in connection_errors.items() if name in connection
            }
        self._raise_errors(provider, parameters, parameter_errors, connection, connection_errors)

    def defaults(self, kind: ModelKind, provider: str, model_name: str) -> dict:
        """Return every setting that has a default, fitted to the model.

        The schema already fits them: a numeric default above the model's limit is the
        limit, and a choice default the model does not offer is null, so it is left out
        ("not set") like any null default.
        """
        properties = self._schemas.parameters_schema(kind, provider, model_name)["properties"]
        return {
            name: fragment["default"]
            for name, fragment in properties.items()
            if fragment["default"] is not None
        }

    def review_reasons(
        self,
        kind: ModelKind,
        provider: str,
        model_name: str,
        parameters: dict,
        connection: dict,
        *,
        custom_model: bool = False,
    ) -> list[str]:
        """Return why a stored config needs review; empty when it matches the catalog. Never raises.

        Connection fields are checked as `validate` checks them, so what an update may keep
        is named too: a required field `connection` lacks, a field the provider does not
        declare, and a secret marker outside a secret field (the run does not send it).

        Args:
            custom_model: The config's model is an organization's own model. One the
                catalog does not know was never in it, so it did not leave it.
        """
        reasons = []
        model = self._repository.model(kind, provider, model_name)
        if model is None:
            if not custom_model:
                reasons.append("Model left the catalog.")
        # Same rule as CatalogRepository.models: deprecated once past the date.
        elif (
            model.deprecation_date is not None and model.deprecation_date < datetime.now(UTC).date()
        ):
            reasons.append("Deprecated model.")
        reasons.extend(
            _reason_lines(
                _errors(self._schemas.parameters_schema(kind, provider, model_name), parameters)
            )
        )
        connection_schema = self._schemas.connection_schema(provider)
        reasons.extend(_reason_lines(_errors(connection_schema, connection)))
        if isinstance(connection, dict):
            # The run drops such a value instead of resolving it (`connection_arguments`).
            secret_fields = _secret_fields(connection_schema)
            reasons.extend(
                f"{name}: {_MARKER_OUTSIDE_SECRET_FIELD}"
                for name, value in connection.items()
                if name not in secret_fields and extract_secret_marker_names({name: value})
            )
        return reasons

    def allowed_parameters(
        self, kind: ModelKind, provider: str, model_name: str, parameters: dict
    ) -> dict:
        """Return the settings a run may send, each fitted to what the catalog allows now.

        Leaves out "not set" settings, settings the model does not take and a choice the
        model no longer offers; a number outside the model's range is sent as the nearest
        limit (a stored temperature of 10 on a model that now allows 8 is sent as 8). The
        stored value is not changed, so the config still shows "needs review".
        """
        properties = self._schemas.parameters_schema(kind, provider, model_name)["properties"]
        allowed = {}
        for name, value in parameters.items():
            fragment = properties.get(name)
            if fragment is None or value is None:
                continue
            if "enum" in fragment:
                if value in fragment["enum"]:
                    allowed[name] = value
                continue
            # bool is an int in Python, but a toggle has no range to fit.
            if isinstance(value, int | float) and not isinstance(value, bool):
                if "maximum" in fragment:
                    value = min(value, fragment["maximum"])
                if "minimum" in fragment:
                    value = max(value, fragment["minimum"])
            allowed[name] = value
        return allowed

    def drop_unsupported(
        self, kind: ModelKind, provider: str, model_name: str, parameters: dict
    ) -> dict:
        """Return `parameters` without the settings the model does not take; values are kept as they are."""
        names = self._repository.parameter_names(kind, provider, model_name)
        return {name: value for name, value in parameters.items() if name in names}

    def drop_undeclared_connection_fields(self, provider: str, connection: dict) -> dict:
        """Return `connection` without the fields the provider does not declare; values are kept as they are."""
        declared = self._schemas.connection_schema(provider)["properties"]
        return {name: value for name, value in connection.items() if name in declared}

    def _connection_errors(
        self, provider: str, connection: object, org_id: int
    ) -> dict[str, list[str]] | list[str]:
        schema = self._schemas.connection_schema(provider)
        errors = _errors(schema, connection)
        if isinstance(errors, dict):
            for field, messages in _marker_errors(
                connection, _secret_fields(schema), org_id
            ).items():
                errors.setdefault(field, []).extend(messages)
        return errors

    def _raise_errors(
        self,
        provider: str,
        parameters: object,
        parameter_errors: dict[str, list[str]] | list[str],
        connection: object,
        connection_errors: dict[str, list[str]] | list[str],
    ) -> None:
        detail = {
            key: errors
            for key, errors in (("parameters", parameter_errors), ("connection", connection_errors))
            if errors
        }
        if not detail:
            return
        provider_spec = self._repository.provider(provider)
        shown_connection_fields = {
            field.name
            for field in (provider_spec.connection_fields if provider_spec else ())
            if not field.secret
        }
        raise ConfigValidationError(
            detail,
            errors=[
                *_error_entries("parameters", parameter_errors, parameters, lambda name: True),
                *_error_entries(
                    "connection",
                    connection_errors,
                    connection,
                    lambda name: name in shown_connection_fields,
                ),
            ],
        )


def _errors(schema: dict, value: object) -> dict[str, list[str]] | list[str]:
    """Return the messages for each key of `value` the schema rejects; a list when it is no object."""
    if not isinstance(value, dict):
        return [_NOT_AN_OBJECT]
    errors = defaultdict(list)
    # Errors on the object itself (unknown and missing keys) name no key, so those two
    # are listed from the schema instead.
    for error in Draft202012Validator(schema).iter_errors(value):
        if error.absolute_path:
            name = str(error.absolute_path[0])
            secret = schema["properties"].get(name, {}).get("x-widget") == "secret"
            errors[name].append(_SECRET_FIELD if secret else error.message)
    for name in sorted(value.keys() - schema["properties"].keys()):
        errors[name].append(_UNKNOWN_KEY)
    for name in schema.get("required", ()):
        if name not in value:
            errors[name].append(_REQUIRED)
    return dict(errors)


def _reason_lines(errors: dict[str, list[str]] | list[str]) -> list[str]:
    if isinstance(errors, list):
        return errors
    return [f"{name}: {message}" for name, messages in errors.items() for message in messages]


def _secret_fields(connection_schema: dict) -> set[str]:
    return {
        name
        for name, fragment in connection_schema["properties"].items()
        if fragment.get("x-widget") == "secret"
    }


def _error_entries(
    part: str, errors: dict[str, list[str]] | list[str], values: object, shows_value
) -> list[dict]:
    """Return one `{"field", "value", "reason"}` entry per message, the field as a dotted path.

    `shows_value(name)` says whether the field's value may be echoed back; it is asked
    with None for the part itself, when the part is not an object.
    """
    if isinstance(errors, list):
        return [_error_entry(part, values, reason, shows_value(None)) for reason in errors]
    return [
        _error_entry(f"{part}.{name}", values.get(name), reason, shows_value(name))
        for name, reasons in errors.items()
        for reason in reasons
    ]


def _error_entry(field: str, value: object, reason: str, shows_value: bool) -> dict:
    if shows_value:
        return {"field": field, "value": value, "reason": reason}
    return {"field": field, "reason": reason}


def _marker_errors(connection: dict, secret_fields: set[str], org_id: int) -> dict[str, list[str]]:
    """Return the errors of the `epicstaff_secret(<name>)` markers in `connection`, per field.

    The run resolves a marker wherever it sits in `connection`, so one outside a secret
    field would put the secret's value into an endpoint or a plain argument. A marker in a
    secret field must name a secret of `org_id`.
    """
    # Parsed per field, so each error names the field holding the marker.
    names_by_field = {
        field: extract_secret_marker_names({field: value}) for field, value in connection.items()
    }
    errors = {
        field: [_MARKER_OUTSIDE_SECRET_FIELD]
        for field, names in names_by_field.items()
        if names and field not in secret_fields
    }
    secret_names_by_field = {
        field: names for field, names in names_by_field.items() if names and field in secret_fields
    }
    if not secret_names_by_field:
        return errors
    # The secret resolver's lookup: the org's own, non-binned secrets by name. Nothing is
    # decrypted, so a value that cannot be decrypted is a run-time error, as today.
    existing = set(
        Secret.objects.filter(
            org_id=org_id, name__in=set().union(*secret_names_by_field.values())
        ).values_list("name", flat=True)
    )
    for field, names in secret_names_by_field.items():
        if names - existing:
            errors[field] = [f"No secret named '{name}'." for name in sorted(names - existing)]
    return errors
