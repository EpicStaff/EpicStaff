from tables.models.tag_models import Tag


class LLMModelTag(Tag):
    class Meta:
        db_table = "tables_llmmodeltag"


class EmbeddingModelTag(Tag):
    class Meta:
        db_table = "tables_embeddingmodeltag"


class LLMConfigTag(Tag):
    class Meta:
        db_table = "tables_llmconfigtag"


class EmbeddingConfigTag(Tag):
    class Meta:
        db_table = "tables_embeddingconfigtag"
