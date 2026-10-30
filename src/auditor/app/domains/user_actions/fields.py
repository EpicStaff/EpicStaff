from app.domains.base import DictFieldCatalog, FreeTextFields
from app.filtering.ast import FieldSpec
from app.filtering.constants import RANGE_OPS, SELECT_OPS, TEXT_CONDITION_OPS

TEXT_FIELDS = ("actor_email", "target_name", "parent_name", "previous_name")

KNOWN_FIELDS: dict[str, FieldSpec] = {
    "id": FieldSpec(RANGE_OPS | SELECT_OPS),
    "event_time": FieldSpec(RANGE_OPS),
    # select fields
    "action": FieldSpec(SELECT_OPS),
    "target_type": FieldSpec(SELECT_OPS),
    "parent_type": FieldSpec(SELECT_OPS),
    # id and keyword fields
    "actor_user_id": FieldSpec(SELECT_OPS | RANGE_OPS, numeric=True),
    "target_id": FieldSpec(SELECT_OPS),
    "parent_id": FieldSpec(SELECT_OPS),
    "actor_api_key_name": FieldSpec(SELECT_OPS),
    "route": FieldSpec(SELECT_OPS),
    # text fields
    **{name: FieldSpec(TEXT_CONDITION_OPS) for name in TEXT_FIELDS},
    # special fields
    "__text__": FieldSpec(frozenset({"contains"})),
}

# Analyzed text splits on '.' and '@' boundaries, so pattern ops run against the
# `.raw` wildcard sub-field, as they do for the sessions `error` field.
WILDCARD_SUBFIELDS: dict[str, str] = {name: f"{name}.raw" for name in TEXT_FIELDS}

USER_ACTIONS_FIELDS = DictFieldCatalog(
    known_fields=KNOWN_FIELDS,
    free_text=FreeTextFields(fields=TEXT_FIELDS),
    wildcard_subfields=WILDCARD_SUBFIELDS,
)
