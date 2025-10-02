from django.db import models


class PythonCode(models.Model):
    code = models.TextField()
    entrypoint = models.TextField(default="main")
    libraries = models.TextField(default="")  # sep: space
    global_kwargs = models.JSONField(default=dict)

    def get_libraries_list(self):
        return list(filter(None, self.libraries.split(" ")))


class PythonCodeTool(models.Model):
    name = models.TextField(unique=True)
    description = models.TextField()
    args_schema = models.JSONField()
    python_code = models.ForeignKey("PythonCode", on_delete=models.CASCADE, null=False)
    favorite = models.BooleanField(default=False)


class PythonCodeResult(models.Model):
    execution_id = models.CharField(max_length=255, primary_key=True)
    result_data = models.TextField(null=True, default=None)
    stderr = models.TextField(default="")
    stdout = models.TextField(default="")
    returncode = models.IntegerField(default=0)
