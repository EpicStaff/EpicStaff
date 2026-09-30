from django.apps import apps
from django.db import models

from rbac.models.author import AuthorModel
from rbac.models.org_scoped import OrgScopedModel

ORG_SCOPED_ORG_LOOKUP = "org_id"


def author_tracked_models() -> list[tuple[type[models.Model], str | None]]:
    """Return `(model, org_lookup)` for every installed model that records an author.

    AuthorModel subclasses supply their own `author_org_lookup` (None when misconfigured);
    OrgScopedModel subclasses reach their org through `org_id`. Proxies and multi-table
    children share their parent's `created_by` column, so only the owning model is listed.
    """
    tracked = []
    for model in apps.get_models():
        if issubclass(model, AuthorModel):
            org_lookup = model.author_org_lookup
        elif issubclass(model, OrgScopedModel):
            org_lookup = ORG_SCOPED_ORG_LOOKUP
        else:
            continue
        if model._meta.get_field("created_by").model is model:
            tracked.append((model, org_lookup))
    return tracked
