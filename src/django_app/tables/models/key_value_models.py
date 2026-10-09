from django.db import models
from django.db.models.functions import Lower
from rbac.models.org_scoped import OrgScopedModel

from tables.constants.key_value_constants import MAX_KEY_LENGTH, MAX_TABLE_NAME_LENGTH
from tables.models.base_models import (
    SoftDeleteFields,
    SoftDeleteMixin,
    TimestampMixin,
    soft_delete_consistency_constraint,
)


class KeyValueTable(OrgScopedModel, TimestampMixin, SoftDeleteMixin):
    # Overrides the nullable OrgScopedModel.org: a brand-new table has nothing to backfill.
    org = models.ForeignKey(
        "rbac.Organization",
        on_delete=models.CASCADE,
        related_name="key_value_tables",
    )
    name = models.CharField(max_length=MAX_TABLE_NAME_LENGTH)
    description = models.TextField(blank=True, default="")

    class Meta(OrgScopedModel.Meta):
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            # Live tables only: a table in the recycle bin keeps its name.
            models.UniqueConstraint(
                Lower("name"),
                "org",
                condition=models.Q(active=True),
                name="unique_key_value_table_name_per_org_ci",
            ),
        ]


class KeyValueTableEntry(TimestampMixin, SoftDeleteFields):
    table = models.ForeignKey(KeyValueTable, on_delete=models.CASCADE, related_name="entries")
    key = models.CharField(max_length=MAX_KEY_LENGTH)
    value = models.JSONField(null=True)
    updated_by_session = models.ForeignKey(
        "Session", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["table", "key"], name="unique_key_value_entry_key_per_table"
            ),
        ]
