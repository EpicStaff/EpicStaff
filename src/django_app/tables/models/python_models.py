from datetime import datetime

from django.db import models

from tables.models.base_models import ContentHashMixin
from tables.models.rbac_models.org_scoped import OrgScopedModel


class PythonCode(ContentHashMixin, models.Model):
    code = models.TextField()
    entrypoint = models.TextField(default="main")
    libraries = models.TextField(default="")  # sep: space
    global_kwargs = models.JSONField(default=dict)

    def get_libraries_list(self):
        return list(filter(None, self.libraries.split(" ")))


class PythonCodeTool(OrgScopedModel, models.Model):
    name = models.TextField()
    description = models.TextField()
    variables = models.JSONField(default=list, blank=True)
    python_code = models.ForeignKey("PythonCode", on_delete=models.CASCADE, null=False)
    favorite = models.BooleanField(default=False)
    built_in = models.BooleanField(default=False)
    use_storage = models.BooleanField(default=False)

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name"],
                name="unique_pythoncodetool_name_per_org",
            ),
        ]


class PythonCodeToolConfig(OrgScopedModel, models.Model):
    name = models.CharField(blank=False, null=False, max_length=255)
    tool = models.ForeignKey("PythonCodeTool", on_delete=models.CASCADE)
    configuration = models.JSONField(default=dict)

    class Meta(OrgScopedModel.Meta):
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
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
