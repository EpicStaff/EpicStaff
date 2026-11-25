from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import models
from tables.management.commands.helpers import load_json_from_file
from tables.management.commands.upload_tools import upload_tools
from tables.models import DefaultRealtimeAgentConfig, RealtimeModel, RealtimeTranscriptionModel

from ai_models.domain.specs import ModelKind, ProviderSpec
from ai_models.models import EmbeddingModel, EmbeddingModelTag, LLMModel, LLMModelTag, Provider
from ai_models.repository import CatalogRepository


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
        upload_default_realtime_agent_config()


REALTIME_MODELS_JSON = "realtime_models.json"
TRANSCRIPTION_MODELS_JSON = "transcription_models.json"

MODEL_JSON_FILES = [
    REALTIME_MODELS_JSON,
    TRANSCRIPTION_MODELS_JSON,
]
PREDEFINED_TAGS = {
    "llm_model": ["recommended"],
    "embedding_model": ["recommended"],
}
# LLM and embedding models come from the model catalog; only the kinds below have rows.
CATALOG_KINDS = (ModelKind.LLM, ModelKind.EMBEDDING)

# The seed files stay with the tables app: django_app/tables/provider_models.
PROVIDER_MODELS_DIR = Path(__file__).resolve().parents[3] / "tables" / "provider_models"


def upload_tags():
    llm_tag_names = PREDEFINED_TAGS["llm_model"]

    for tag in llm_tag_names:
        LLMModelTag.objects.update_or_create(name=tag, defaults={"predefined": True})

    LLMModelTag.objects.filter(predefined=True).exclude(name__in=llm_tag_names).delete()

    embed_tag_names = PREDEFINED_TAGS["embedding_model"]

    for tag in embed_tag_names:
        EmbeddingModelTag.objects.update_or_create(name=tag, defaults={"predefined": True})

    EmbeddingModelTag.objects.filter(predefined=True).exclude(name__in=embed_tag_names).delete()


def get_all_providers_from_files():
    all_providers = set()
    for path in MODEL_JSON_FILES:
        js_path = PROVIDER_MODELS_DIR / path
        data = load_json_from_file(js_path)
        all_providers.update(data.keys())
    return all_providers


def upload_providers():
    """Create a row for each catalog provider a user can pick and each realtime seed provider.

    A catalog provider that already has a row under its name or any of its aliases keeps
    that row: a second row for the same provider is never created.
    """
    repository = CatalogRepository.default()
    for kind in CATALOG_KINDS:
        for provider in repository.providers(kind):
            _provider_row(provider)

    for name in get_all_providers_from_files():
        Provider.objects.get_or_create(name=name)


def upload_llm_models():
    _upload_catalog_models(ModelKind.LLM, LLMModel, "llm_provider", LLMModelTag, "llm_models")


def upload_embedding_models():
    _upload_catalog_models(
        ModelKind.EMBEDDING,
        EmbeddingModel,
        "embedding_provider",
        EmbeddingModelTag,
        "embedding_models",
    )


def _provider_row(provider: ProviderSpec) -> Provider:
    """Return the provider's row, preferring its own name over an alias; create it when missing."""
    names = (provider.name, *provider.aliases)
    rows = {row.name: row for row in Provider.objects.filter(name__in=names)}
    existing = next((rows[name] for name in names if name in rows), None)
    return existing or Provider.objects.create(name=provider.name)


def _upload_catalog_models(
    kind: ModelKind,
    model_class: type[models.Model],
    provider_field: str,
    tag_class: type[models.Model],
    tag_relation: str,
) -> None:
    """Create or update the built-in rows of `kind` from the catalog, and hide the rest.

    Only providers the catalog offers for `kind` get rows, deprecated models included,
    so configs on them keep working. An existing built-in row matches a catalog model
    the way LiteLLM looks its name up and keeps its stored name and id; a new row takes
    the catalog's name. A built-in row the catalog does not list is hidden, never
    deleted, because configs may use it. Rows an organization owns are never touched.
    """
    repository = CatalogRepository.default()
    recommended_tag, _ = tag_class.objects.get_or_create(
        name="recommended", defaults={"predefined": True}
    )
    builtin_rows = model_class.objects.filter(org__isnull=True, is_custom=False)

    row_ids_by_model = defaultdict(list)
    for row in builtin_rows.select_related(provider_field):
        provider = getattr(row, provider_field)
        model = repository.model(kind, provider.name, row.name) if provider else None
        if model is not None:
            row_ids_by_model[model.provider, model.name].append(row.pk)

    # (recommended, row id) for every row the catalog lists.
    seeded: list[tuple[bool, int]] = []
    new_rows: list[tuple[bool, models.Model]] = []
    for provider in repository.providers(kind):
        provider_row = _provider_row(provider)
        for model in repository.models(kind, provider.name, include_deprecated=True):
            row_ids = row_ids_by_model.get((model.provider, model.name))
            if row_ids is None:
                new_row = model_class(
                    name=model.name, predefined=True, **{provider_field: provider_row}
                )
                new_rows.append((model.recommended, new_row))
            else:
                seeded.extend((model.recommended, row_id) for row_id in row_ids)
    model_class.objects.bulk_create([row for _, row in new_rows])
    seeded.extend((recommended, row.pk) for recommended, row in new_rows)

    if not seeded:
        # An empty catalog must never hide every model.
        return
    seeded_ids = [row_id for _, row_id in seeded]
    builtin_rows.filter(pk__in=seeded_ids).update(predefined=True, is_visible=True)
    builtin_rows.exclude(pk__in=seeded_ids).update(is_visible=False)

    tagged_models = getattr(recommended_tag, tag_relation)
    tagged_models.add(*(row_id for recommended, row_id in seeded if recommended))
    tagged_models.remove(*(row_id for recommended, row_id in seeded if not recommended))


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
    RealtimeTranscriptionModel.objects.filter(is_custom=False, org__isnull=True).exclude(
        pk__in=active_ids
    ).delete()


def upload_default_realtime_agent_config():
    DefaultRealtimeAgentConfig.objects.all().delete()
    DefaultRealtimeAgentConfig.objects.create(id=1)
