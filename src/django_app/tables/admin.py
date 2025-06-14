from django.contrib import admin
from .models import (
    Provider,
    LLMModel,
    EmbeddingModel,
    Tool,
    Agent,
    Crew,
    Task,
    ConfigLLM,
)

admin.site.register(Provider)
admin.site.register(LLMModel)
admin.site.register(EmbeddingModel)
admin.site.register(Tool)
admin.site.register(Agent)
admin.site.register(Crew)
admin.site.register(Task)
admin.site.register(ConfigLLM)
