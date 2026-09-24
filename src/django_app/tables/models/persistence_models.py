from django.db import models
from django.db.models.functions import Lower
from rbac.models.org_scoped import OrgScopedModel

from tables.constants.persistence_constants import MAX_KEY_LENGTH, MAX_TABLE_NAME_LENGTH
from tables.models.base_models import TimestampMixin


class PersistenceTable(OrgScopedModel, TimestampMixin):
    # Overrides the nullable OrgScopedModel.org: a brand-new table has nothing to backfill.
    org = models.ForeignKey(
        "rbac.Organization",
        on_delete=models.CASCADE,
        related_name="persistence_tables",
    )
    name = models.CharField(max_length=MAX_TABLE_NAME_LENGTH)
    description = models.TextField(blank=True, default="")

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "org", name="unique_persistence_table_name_per_org_ci"
            ),
        ]


class PersistenceTableEntry(TimestampMixin):
    table = models.ForeignKey(PersistenceTable, on_delete=models.CASCADE, related_name="entries")
    key = models.CharField(max_length=MAX_KEY_LENGTH)
    value = models.JSONField(null=True)
    updated_by_session = models.ForeignKey(
        "Session", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["table", "key"], name="unique_persistence_entry_key_per_table"
            ),
        ]
