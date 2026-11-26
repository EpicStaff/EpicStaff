import sys

from django.apps import AppConfig


class AIModelsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ai_models"

    def ready(self):
        # Elect a single owner across web-server workers to run the daily
        # litellm model-cost refresh when LITELLM_MODEL_COST_REFRESH_ENABLED is on;
        # skip during migrate/makemigrations/tests.
        argv0 = sys.argv[0] if sys.argv else ""
        is_web_server = (
            "runserver" in sys.argv
            or "gunicorn" in argv0
            or "uvicorn" in argv0
            or "daphne" in argv0
        )
        if is_web_server:
            from ai_models.utils.litellm_model_info import start_litellm_refresh_if_owner

            start_litellm_refresh_if_owner()
