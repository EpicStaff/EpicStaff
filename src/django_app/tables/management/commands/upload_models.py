from pathlib import Path
from django.core.management.base import BaseCommand

from tables.models import (
    EmbeddingModel,
    LLMModel,
    Provider,
    RealtimeModel,
    RealtimeTranscriptionModel,
    DefaultRealtimeAgentConfig,
)
from tables.models.crew_models import (
    Agent,
    DefaultAgentConfig,
    DefaultCrewConfig,
)
from tables.models.embedding_models import DefaultEmbeddingConfig
from tables.models.llm_models import DefaultLLMConfig
from tables.management.commands.helpers import load_json_from_file
from tables.management.commands.upload_tools import upload_tools
from tables.models.tag_models import LLMModelTag, EmbeddingModelTag


class Command(BaseCommand):
    help = "Upload predefined models to database"

    def handle(self, *args, **kwargs):
        upload_tags()
        upload_providers()
        upload_llm_models()
        upload_realtime_agent_models()
        upload_realtime_transcription_models()
        upload_embedding_models()
        upload_tools()
        upload_default_llm_config()
        upload_default_embedding_config()
        upload_default_realtime_agent_config()
        upload_default_agent_config()
        upload_default_crew_config()
        upload_realtime_agents()


LLM_MODELS_JSON = "llm_models.json"
EMBEDDING_MODELS_JSON = "embedding_models.json"
REALTIME_MODELS_JSON = "realtime_models.json"
TRANSCRIPTION_MODELS_JSON = "transcription_models.json"

MODEL_JSON_FILES = [
    LLM_MODELS_JSON,
    EMBEDDING_MODELS_JSON,
    REALTIME_MODELS_JSON,
    TRANSCRIPTION_MODELS_JSON,
]
PREDEFINED_TAGS = {
    "llm_model": ["recommended"],
    "embedding_model": ["recommended"],
}

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROVIDER_MODELS_DIR = BASE_DIR / "provider_models"


def upload_tags():
    llm_tag_names = PREDEFINED_TAGS["llm_model"]

    for tag in llm_tag_names:
        LLMModelTag.objects.update_or_create(name=tag, defaults={"predefined": True})

    LLMModelTag.objects.filter(predefined=True).exclude(name__in=llm_tag_names).delete()

    embed_tag_names = PREDEFINED_TAGS["embedding_model"]

    for tag in embed_tag_names:
        EmbeddingModelTag.objects.update_or_create(
            name=tag, defaults={"predefined": True}
        )

    EmbeddingModelTag.objects.filter(predefined=True).exclude(
        name__in=embed_tag_names
    ).delete()


def get_all_providers_from_files():
    all_providers = set()
    for path in MODEL_JSON_FILES:
        js_path = PROVIDER_MODELS_DIR / path
        data = load_json_from_file(js_path)
        all_providers.update(data.keys())
    return all_providers


def upload_providers():
    current_provider_names = get_all_providers_from_files()
    for name in current_provider_names:
        Provider.objects.get_or_create(name=name)

    # Provider.objects.exclude(name__in=current_provider_names).delete()


def upload_llm_models():
    path = PROVIDER_MODELS_DIR / LLM_MODELS_JSON
    models_by_provider = load_json_from_file(path)

    recommended_tag, _ = LLMModelTag.objects.get_or_create(
        name="recommended", defaults={"predefined": True}
    )

    active_ids = []

    for provider_name, model_list in models_by_provider.items():
        provider, _ = Provider.objects.get_or_create(name=provider_name)

        for model_data in model_list:
            model_name = model_data["name"]
            is_recommended = model_data["recommended"]
            is_deprecated = model_data.get("deprecated", False)

            llm_model, _ = LLMModel.objects.update_or_create(
                llm_provider=provider,
                name=model_name,
                org__isnull=True,
                defaults={
                    "predefined": True,
                    "is_visible": not is_deprecated,
                },
            )

            if is_recommended:
                llm_model.tags.add(recommended_tag)
            else:
                llm_model.tags.remove(recommended_tag)

            active_ids.append(llm_model.pk)

    if not active_ids:
        return
    LLMModel.objects.filter(predefined=True, is_custom=False, org__isnull=True).exclude(
        pk__in=active_ids
    ).delete()


def upload_realtime_agent_models():
    path = PROVIDER_MODELS_DIR / REALTIME_MODELS_JSON
    models_by_provider = load_json_from_file(path)

    active_ids = []

    for provider_name, model_names in models_by_provider.items():
        provider, _ = Provider.objects.get_or_create(name=provider_name)
        for model_name in model_names:
            realtime_model, _ = RealtimeModel.objects.get_or_create(
                name=model_name, provider=provider, org__isnull=True
            )
            active_ids.append(realtime_model.pk)

    if not active_ids:
        return
    RealtimeModel.objects.filter(is_custom=False, org__isnull=True).exclude(
        pk__in=active_ids
    ).delete()


def upload_realtime_transcription_models():
    path = PROVIDER_MODELS_DIR / TRANSCRIPTION_MODELS_JSON
    models_by_provider = load_json_from_file(path)

    active_ids = []

    for provider_name, model_names in models_by_provider.items():
        provider, _ = Provider.objects.get_or_create(name=provider_name)
        for model_name in model_names:
            transcription_model, _ = RealtimeTranscriptionModel.objects.get_or_create(
                name=model_name, provider=provider, org__isnull=True
            )
            active_ids.append(transcription_model.pk)

    if not active_ids:
        return
    RealtimeTranscriptionModel.objects.filter(
        is_custom=False, org__isnull=True
    ).exclude(pk__in=active_ids).delete()


def upload_embedding_models():
    path = PROVIDER_MODELS_DIR / EMBEDDING_MODELS_JSON
    models_by_provider = load_json_from_file(path)

    recommended_tag, _ = EmbeddingModelTag.objects.get_or_create(
        name="recommended", defaults={"predefined": True}
    )

    active_ids = []

    for provider_name, model_list in models_by_provider.items():
        provider, _ = Provider.objects.get_or_create(name=provider_name)

        for model_data in model_list:
            model_name = model_data["name"]
            is_recommended = model_data["recommended"]

            embedding_model, _ = EmbeddingModel.objects.update_or_create(
                embedding_provider=provider,
                name=model_name,
                org__isnull=True,
                defaults={
                    "predefined": True,
                },
            )

            if is_recommended:
                embedding_model.tags.add(recommended_tag)
            else:
                embedding_model.tags.remove(recommended_tag)

            active_ids.append(embedding_model.pk)

    if not active_ids:
        return
    EmbeddingModel.objects.filter(
        predefined=True, is_custom=False, org__isnull=True
    ).exclude(pk__in=active_ids).delete()


def upload_realtime_agents():
    from tables.models.realtime_models import RealtimeAgent

    agent_list = Agent.objects.all()
    for agent in agent_list:
        RealtimeAgent.objects.get_or_create(
            agent=agent,
            defaults={
                "wake_word": None,
                "stop_prompt": None,
                "language": None,
            },
        )

    pass


def upload_default_llm_config():
    DefaultLLMConfig.objects.filter().delete()
    DefaultLLMConfig.objects.create(id=1)


def upload_default_embedding_config():
    DefaultEmbeddingConfig.objects.filter().delete()
    DefaultEmbeddingConfig.objects.create(id=1)


def upload_default_agent_config():
    DefaultAgentConfig.objects.all().delete()
    DefaultAgentConfig.objects.create(id=1)


def upload_default_realtime_agent_config():
    DefaultRealtimeAgentConfig.objects.all().delete()
    DefaultRealtimeAgentConfig.objects.create(id=1)


def upload_default_crew_config():
    DefaultCrewConfig.objects.all().delete()
    DefaultCrewConfig.objects.create(id=1)
