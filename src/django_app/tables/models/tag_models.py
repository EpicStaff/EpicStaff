from django.db import models


class Tag(models.Model):
    name = models.CharField()
    predefined = models.BooleanField(default=False)

    class Meta:
        abstract = True


class CrewTag(Tag): ...


class AgentTag(Tag): ...


class GraphTag(Tag): ...


class LLMModelTag(Tag): ...


class EmbeddingModelTag(Tag): ...


class LLMConfigTag(Tag): ...
