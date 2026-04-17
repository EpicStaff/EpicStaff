from django.contrib import admin
from django.utils import timezone
from .models import (
    Agent,
    Tool,
    ToolConfig,
    ToolConfigField,
    DefaultCrewConfig,
    DefaultAgentConfig,
    DefaultToolConfig,
)
from .models import ApiKey
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


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "prefix", "is_revoked", "last_used_at", "created_at")
    search_fields = ("name", "prefix")
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at", "revoked_at")
    actions = ["revoke_keys"]

    def save_model(self, request, obj, form, change):
        if not change:
            raw_key = ApiKey.generate_raw_key()
            obj.set_key(raw_key)
            super().save_model(request, obj, form, change)
            self.message_user(
                request,
                f"API key created. Copy this key now: {raw_key}",
                level="WARNING",
            )
            return
        super().save_model(request, obj, form, change)

    def revoke_keys(self, request, queryset):
        queryset.update(revoked_at=timezone.now())

    revoke_keys.short_description = "Revoke selected API keys"
