from django.conf import settings
from django.db import models


class OrganizationUser(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_memberships",
    )
    org = models.ForeignKey(
        "Organization", on_delete=models.CASCADE, related_name="members"
    )
    role = models.ForeignKey(
        "Role", on_delete=models.CASCADE, related_name="organization_users"
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rbac_organization_user"
        unique_together = (("user", "org"),)

    def __str__(self) -> str:
        return f"user={self.user_id} org={self.org_id} role={self.role_id}"
