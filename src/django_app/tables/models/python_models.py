from django.db import models

from tables.models.base_models import ContentHashMixin


class PythonCode(ContentHashMixin, models.Model):
    code = models.TextField()
    entrypoint = models.TextField(default="main")
    libraries = models.TextField(default="")  # sep: space
    global_kwargs = models.JSONField(default=dict)

    def get_libraries_list(self):
        return list(filter(None, self.libraries.split(" ")))


class PythonCodeTool(models.Model):
    name = models.TextField(unique=True)
    description = models.TextField()
    variables = models.JSONField(default=list, blank=True)
    python_code = models.ForeignKey("PythonCode", on_delete=models.CASCADE, null=False)
    favorite = models.BooleanField(default=False)
    built_in = models.BooleanField(default=False)
    use_storage = models.BooleanField(default=False)


class PythonCodeToolConfig(models.Model):
    name = models.CharField(blank=False, null=False, max_length=255)
    tool = models.ForeignKey("PythonCodeTool", on_delete=models.CASCADE)
    configuration = models.JSONField(default=dict)

    class Meta:
        unique_together = (
            "tool",
            "name",
        )


class PythonCodeResult(models.Model):
    execution_id = models.CharField(max_length=255, primary_key=True)
    result_data = models.TextField(null=True, default=None)
    stderr = models.TextField(default="")
    stdout = models.TextField(default="")
    returncode = models.IntegerField(default=0)
