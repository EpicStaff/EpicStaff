from django.apps import apps
from django.core import checks
from django.core.exceptions import FieldDoesNotExist

from rbac.authorship.registry import author_tracked_models

MISSING_ORG_LOOKUP_CHECK_ID = "rbac.E001"
MISCONFIGURED_OWNER_FIELD_CHECK_ID = "rbac.E002"


@checks.register(checks.Tags.models)
def check_author_models(app_configs, **kwargs) -> list[checks.Error]:
    """Report concrete AuthorModel subclasses that do not declare `author_org_lookup`."""
    return [
        checks.Error(
            f"{model.__name__} inherits AuthorModel but does not set author_org_lookup.",
            hint=(
                "Set author_org_lookup to the ORM lookup from a row to its organization "
                "id, e.g. 'graph__org_id'."
            ),
            obj=model,
            id=MISSING_ORG_LOOKUP_CHECK_ID,
        )
        for model, org_lookup in author_tracked_models()
        if org_lookup is None and (app_configs is None or model._meta.app_config in app_configs)
    ]


@checks.register(checks.Tags.models)
def check_last_edit_owner_fields(app_configs, **kwargs) -> list[checks.Error]:
    """Report models whose `last_edit_owner_field` does not name one of their foreign keys."""
    return [
        checks.Error(
            f"{model.__name__}.last_edit_owner_field names {owner_field_name!r}, "
            "which is not a foreign key of the model.",
            hint="Name the model's foreign key to its owner, or set last_edit_owner_field = None.",
            obj=model,
            id=MISCONFIGURED_OWNER_FIELD_CHECK_ID,
        )
        for model in apps.get_models()
        if (owner_field_name := getattr(model, "last_edit_owner_field", None)) is not None
        and not _is_foreign_key(model, owner_field_name)
        and (app_configs is None or model._meta.app_config in app_configs)
    ]


def _is_foreign_key(model, field_name: str) -> bool:
    try:
        return model._meta.get_field(field_name).many_to_one
    except FieldDoesNotExist:
        return False
