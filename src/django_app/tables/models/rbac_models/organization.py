from django.db import models
from django.db.models import Q, UniqueConstraint
from django.db.models.functions import Lower


class Organization(models.Model):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rbac_organization"
        constraints = [
            UniqueConstraint(
                Lower("name"),
                name="rbac_organization_name_ci_uniq",
            ),
            UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="rbac_organization_single_default",
            ),
        ]

    def __str__(self) -> str:
        return self.name
