from django.contrib import admin
from .models import (
    Agent,
    Tool,
    ToolConfig,
    ToolConfigField,
    DefaultCrewConfig,
    DefaultAgentConfig,
    DefaultToolConfig,
)
from .models import LLMConfig
from .models import EmbeddingModel
from .models import Provider
from .models import LLMModel
from .models import Crew
from .models import (
    Task,
)
from .models.realtime_models import DefaultRealtimeAgentConfig
from .models.default_models import DefaultModels

admin.site.register(Provider)
admin.site.register(LLMModel)
admin.site.register(EmbeddingModel)
admin.site.register(Tool)
admin.site.register(Agent)
admin.site.register(Crew)
admin.site.register(Task)
admin.site.register(LLMConfig)
admin.site.register(ToolConfigField)
admin.site.register(ToolConfig)

# Default configs
admin.site.register(DefaultCrewConfig)
admin.site.register(DefaultAgentConfig)
admin.site.register(DefaultRealtimeAgentConfig)
admin.site.register(DefaultToolConfig)
admin.site.register(DefaultModels)
