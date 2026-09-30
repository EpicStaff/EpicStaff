from django.core import checks

from rbac.authorship.registry import author_tracked_models

MISSING_ORG_LOOKUP_CHECK_ID = "rbac.E001"


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
