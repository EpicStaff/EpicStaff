from django.db import models


class Provider(models.Model):
    name = models.TextField(unique=True)

    class Meta:
        db_table = "tables_provider"

    def __str__(self):
        return self.name
