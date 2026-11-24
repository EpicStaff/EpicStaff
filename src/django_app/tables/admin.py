from ai_models.models import DefaultModels, EmbeddingModel, LLMConfig, LLMModel, Provider
from django.contrib import admin

from .models import Agent, Task
from .models.realtime_models import DefaultRealtimeAgentConfig

admin.site.register(Provider)
admin.site.register(LLMModel)
admin.site.register(EmbeddingModel)
admin.site.register(Agent)
admin.site.register(Task)
admin.site.register(LLMConfig)

# Default configs
admin.site.register(DefaultRealtimeAgentConfig)
admin.site.register(DefaultModels)
