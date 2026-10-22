from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from rbac.authorship import resolve_author
from tables.services.secrets.linked_ids import linked_ids
from tables.services.secrets.reference_guard import (
    SecretActor,
    SecretChange,
    SecretDestinationChange,
    SecretReferenceChange,
)
from tables.services.secrets.secret_resolver import extract_secret_marker_names

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


def _nothing_persisted(source: str) -> None:
    return None


@dataclass(frozen=True)
class RowWrite:
    """One row's pending write, as plain data so a policy runs without DRF.

    Attributes:
        instance: The persisted row, or None when the write creates one.
        attrs: The incoming values, keyed by model attribute (a DRF field's source).
        writable_fields: {field name: source} for every field the writer may set. A
            policy names its fields by field name, which is also the error key.
        persisted_value: Reads what the persisted row holds at a source. A nested
            serializer has no instance of its own, so this is not always
            `getattr(instance, source)`.
    """

    instance: object | None
    attrs: Mapping[str, object]
    writable_fields: Mapping[str, str]
    persisted_value: Callable[[str], object]

    @classmethod
    def for_new_row(cls, attrs: Mapping[str, object]) -> "RowWrite":
        """A write creating a row from `attrs`, every key writable under its own name."""
        return cls(
            instance=None,
            attrs=attrs,
            writable_fields={name: name for name in attrs},
            persisted_value=_nothing_persisted,
        )

    @classmethod
    def of_persisted_row(cls, instance) -> "RowWrite":
        """A write changing nothing on `instance`, to ask a policy about the row as saved."""
        return cls(
            instance=instance,
            attrs={},
            writable_fields={},
            persisted_value=lambda source: getattr(instance, source, None),
        )

    def persisted(self) -> "RowWrite":
        """The same row with nothing incoming, so every value reads as persisted."""
        return replace(self, attrs={})

    def value_after_save(self, source: str, *, persisted_attribute: str | None = None):
        """The value `source` holds once the write is saved: the incoming one, else the persisted one.

        `persisted_attribute` reads a different attribute off the persisted row --
        pass `<fk>_id` to test an FK for presence without loading the related row.
        """
        if source in self.attrs:
            return self.attrs[source]
        return self.persisted_value(persisted_attribute or source)

    def writable_values_after_save(self, *, exclude: frozenset[str]) -> dict:
        """{field name: value once saved} for every writable field not in `exclude`.

        Related rows compare by pk. Built for a model row's destination: listing the
        fields that do NOT route (rather than those that do) keeps a field added later
        gated until someone decides it is cosmetic.
        """
        values = {}
        for name, source in self.writable_fields.items():
            if name in exclude:
                continue
            value = self.value_after_save(source)
            # Blank and null route the same, and the frontend sends null for an emptied
            # field; treating them as different would deny a save that changes nothing.
            values[name] = None if value == "" else getattr(value, "pk", value)
        return values


class SecretPolicy:
    """What a write to one kind of row may not change without secrets:USE.

    Declare what applies to the row:

    - `reference_fields`: FK/M2M fields that point at a Secret.
    - `header_fields`: JSON header fields whose `epicstaff_secret(<name>)` markers
      resolve to org secrets by name.
    - `destination` + `carries_secret`: override both when the row decides where a
      secret-bearing request goes -- its own base URL, every routing field of a model
      row (`RowWrite.writable_values_after_save`), or an FK to a model
      (`model_destination`).
    - `approval_model` + `approval_label`: set on a subclass whose row is a
      SecretBindingApprovedModel, so SecretReferenceGuard records who approved its secret
      binding and SecretInjectionGuard checks that approver; the label names the row in
      an injection denial.

    A field the writer does not expose as writable is skipped, so one policy serves a
    serializer and a narrower variant of it alike. A policy that only lists fields is a
    plain instance (`SecretPolicy(reference_fields=(...))`); one that decides a
    destination or records an approver is a subclass.
    """

    reference_fields: tuple[str, ...] = ()
    header_fields: tuple[str, ...] = ()
    approval_model: type | None = None
    approval_label: str = ""

    def __init__(
        self,
        *,
        reference_fields: tuple[str, ...] | None = None,
        header_fields: tuple[str, ...] | None = None,
    ):
        if reference_fields is not None:
            self.reference_fields = reference_fields
        if header_fields is not None:
            self.header_fields = header_fields

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(reference_fields={self.reference_fields!r}, "
            f"header_fields={self.header_fields!r})"
        )

    @property
    def records_binding_approval(self) -> bool:
        return self.approval_model is not None

    def binding_approval(self, actor: SecretActor) -> dict:
        """The attrs recording `actor` as approver of the row's secret binding.

        Empty for a row that records no approver. An actor that is not a person (the
        system API-key principal) records NULL. Whether to call this at all is
        SecretReferenceGuard's decision (`authorize_write`, `approval_by_use_holder`).
        """
        if not self.records_binding_approval:
            return {}
        return {"secret_binding_approved_by": resolve_author(actor.user)}

    def destination(self, write: RowWrite) -> dict:
        """Where a request carrying this row's secrets goes once `write` is saved, as {field name: value}.

        The default declares none, so the destination is never gated.
        """
        return {}

    def carries_secret(self, write: RowWrite) -> bool:
        """Whether a secret travels to this row's destination once `write` is saved."""
        return False

    def sends_secret_to_custom_destination(self, write: RowWrite) -> bool:
        """Whether the row, once `write` is saved, sends a secret anywhere but the trusted catalog.

        A destination value that is empty or CATALOG_DESTINATION is trusted; any other
        value -- a custom model, an own base_url -- is custom. Reads only the row and the
        relations `destination` reads, so it is free when those are already loaded. Pass
        `RowWrite.of_persisted_row(instance)` to ask about the saved row.
        """
        destination = self.destination(write)
        if all(value in (None, "", CATALOG_DESTINATION) for value in destination.values()):
            return False
        return self.carries_secret(write)

    def changes(self, write: RowWrite) -> list[SecretChange]:
        """Describe `write` to SecretReferenceGuard: one change per guarded field it sets.

        Unchanged fields are included; the guard decides what counts as a change. The
        destination is left out on create -- a new row reaches a secret only through a
        reference, which the other changes already cover -- and whenever it is
        unchanged or carries no secret, so `carries_secret`'s queries run only for a
        destination that actually moves.
        """
        changes: list[SecretChange] = []
        for field_name, source in self._sources_written(write, self.reference_fields):
            changes.append(
                SecretReferenceChange(
                    field_name=field_name,
                    incoming=linked_ids(write.attrs[source]),
                    current=linked_ids(write.persisted_value(source)),
                )
            )
        for field_name, source in self._sources_written(write, self.header_fields):
            changes.append(
                SecretReferenceChange(
                    field_name=field_name,
                    incoming=frozenset(extract_secret_marker_names(write.attrs[source])),
                    current=frozenset(extract_secret_marker_names(write.persisted_value(source))),
                )
            )
        if write.instance is not None:
            destination_change = SecretDestinationChange(
                incoming=self.destination(write), current=self.destination(write.persisted())
            )
            if destination_change.changed_field_name() is not None and self.carries_secret(write):
                changes.append(destination_change)
        return changes

    @staticmethod
    def _sources_written(write: RowWrite, field_names: tuple[str, ...]):
        for field_name in field_names:
            source = write.writable_fields.get(field_name)
            if source is not None and source in write.attrs:
                yield field_name, source
