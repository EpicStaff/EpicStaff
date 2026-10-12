from django.db import models
from django.db.models import Prefetch
from rbac.models.last_edit import LastEditTrackedModel
from rbac.models.org_scoped import OrgScopedModel

from tables.models.base_models import (
    ActiveManager,
    ContentHashMixin,
    SoftDeleteFields,
    SoftDeleteMixin,
    TimestampMixin,
    soft_delete_consistency_constraint,
)

#: Where `linked_secrets_prefetch()` puts a PythonCode's secrets, binned ones included.
LINKED_SECRETS_ATTR = "prefetched_linked_secrets"


def linked_secrets_prefetch(python_code_path: str) -> Prefetch:
    """Prefetch the secrets the PythonCode at `python_code_path` links to, for `linked_secrets()`."""
    secret_model = PythonCode.secrets.field.related_model
    return Prefetch(
        f"{python_code_path}__secrets",
        queryset=secret_model.all_objects.all(),
        to_attr=LINKED_SECRETS_ATTR,
    )


class PythonCode(ContentHashMixin, models.Model):
    code = models.TextField()
    entrypoint = models.TextField(default="main")
    libraries = models.TextField(default="")  # sep: space
    global_kwargs = models.JSONField(default=dict)
    secrets = models.ManyToManyField("Secret", blank=True, related_name="python_codes")

    def linked_secrets(self):
        """Every secret this code links to, binned ones included: they stay linked until purged.

        For editing only. Running the code reads `secrets` (live only), so a binned secret
        is never delivered. Uses `linked_secrets_prefetch()` when the query added it; a plain
        `secrets` prefetch can't be used, since its cache holds live secrets only.
        """
        prefetched = getattr(self, LINKED_SECRETS_ATTR, None)
        if prefetched is not None:
            return prefetched
        return list(self.secrets.model.all_objects.filter(python_codes=self))

    def forget_linked_secrets(self) -> None:
        """Drop the prefetched list after the links change: a plain attribute, so nothing else does."""
        self.__dict__.pop(LINKED_SECRETS_ATTR, None)

    def get_libraries_list(self):
        return list(filter(None, self.libraries.split(" ")))


class PythonCodeTool(
    OrgScopedModel, LastEditTrackedModel, TimestampMixin, SoftDeleteMixin, models.Model
):
    objects = ActiveManager()
    all_objects = models.Manager()

    name = models.TextField()
    description = models.TextField()
    variables = models.JSONField(default=list, blank=True)
    python_code = models.ForeignKey("PythonCode", on_delete=models.CASCADE, null=False)
    built_in = models.BooleanField(default=False)
    use_storage = models.BooleanField(default=False)
    labels = models.ManyToManyField("Label", blank=True, related_name="python_code_tools")

    class Meta(OrgScopedModel.Meta):
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["org", "name"],
                condition=models.Q(active=True),
                name="unique_pythoncodetool_name_per_org",
            ),
        ]

    def records_last_edit(self) -> bool:
        # Built-in tools are shared by every organization; an editor of one org
        # must not be shown to the others.
        return not self.built_in


class PythonCodeToolConfig(OrgScopedModel, SoftDeleteFields):
    name = models.CharField(blank=False, null=False, max_length=255)
    tool = models.ForeignKey("PythonCodeTool", on_delete=models.CASCADE)
    configuration = models.JSONField(default=dict)

    class Meta(OrgScopedModel.Meta):
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]
        unique_together = (
            "org",
            "tool",
            "name",
        )


class PythonCodeResult(OrgScopedModel, models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        COMPLETED = "completed"
        ERROR = "error"

    python_code = models.ForeignKey(
        "PythonCode", on_delete=models.SET_NULL, null=True, related_name="executions"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, default=None)

    execution_id = models.CharField(max_length=255, primary_key=True)
    result_data = models.TextField(null=True, default=None)
    stderr = models.TextField(default="")
    stdout = models.TextField(default="")
    returncode = models.IntegerField(null=True, default=None)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
