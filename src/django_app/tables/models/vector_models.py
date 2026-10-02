import uuid

from django.db import models
from pgvector.django import HnswIndex, VectorField


class MemoryDatabase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vector = VectorField(
        dimensions=1536,
        null=True,
        blank=True,
    )
    payload = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            HnswIndex(
                name="vector_index",
                fields=["vector"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            )
        ]
