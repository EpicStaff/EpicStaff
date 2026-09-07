import pytest

from tables.management.commands import upload_models
from tables.models import Provider
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import (
    LLMModel,
    RealtimeModel,
    RealtimeTranscriptionModel,
)
from tables.models.rbac_models import Organization


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org A")


@pytest.mark.django_db
def test_seeding_survives_org_row_colliding_with_realtime_builtin(org):
    """An org-owned RealtimeModel sharing a built-in's (name, provider) must not
    break upload_models, and must not be adopted into the catalog."""
    upload_models.Command().handle()

    provider = Provider.objects.get(name="openai")
    collision_name = "gpt-4o-mini-realtime-preview-2024-12-17"
    org_row = RealtimeModel.objects.create(
        name=collision_name, provider=provider, org=org, is_custom=True
    )

    upload_models.Command().handle()

    org_row.refresh_from_db()
    assert org_row.org_id == org.id
    assert org_row.is_custom is True
    assert (
        RealtimeModel.objects.filter(
            name=collision_name, provider=provider, org__isnull=True
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_seeding_survives_org_row_colliding_with_transcription_builtin(org):
    """Same guarantee for the transcription registry, whose name defaults to
    'whisper-1' — also present in the seed list."""
    upload_models.Command().handle()

    provider = Provider.objects.get(name="openai")
    org_row = RealtimeTranscriptionModel.objects.create(
        name="whisper-1", provider=provider, org=org, is_custom=True
    )

    upload_models.Command().handle()

    org_row.refresh_from_db()
    assert org_row.org_id == org.id
    assert org_row.is_custom is True
    assert (
        RealtimeTranscriptionModel.objects.filter(
            name="whisper-1", provider=provider, org__isnull=True
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_seeding_never_adopts_an_org_llm_model(org):
    """An org's custom row sharing a catalog (name, provider) must not be flipped
    into a predefined built-in visible to every tenant."""
    upload_models.Command().handle()
    provider = Provider.objects.get(name="openai")

    org_row = LLMModel.objects.create(
        name="org-only-model",
        llm_provider=provider,
        org=org,
        is_custom=True,
        predefined=False,
    )

    upload_models.Command().handle()

    org_row.refresh_from_db()
    assert org_row.org_id == org.id
    assert org_row.is_custom is True
    assert org_row.predefined is False, "seeding adopted an org-owned row"


@pytest.mark.django_db
def test_prune_never_deletes_an_org_row(org):
    """The prune removes catalog rows that left the JSON. It must not reach rows
    an organization owns, whatever their flags."""
    upload_models.Command().handle()
    provider = Provider.objects.get(name="openai")

    keep = LLMModel.objects.create(
        name="not-in-any-json",
        llm_provider=provider,
        org=org,
        is_custom=True,
        predefined=True,
    )
    keep_emb = EmbeddingModel.objects.create(
        name="not-in-any-json-emb",
        embedding_provider=provider,
        org=org,
        is_custom=True,
        predefined=True,
    )

    upload_models.Command().handle()

    assert LLMModel.objects.filter(id=keep.id).exists()
    assert EmbeddingModel.objects.filter(id=keep_emb.id).exists()


@pytest.mark.django_db
def test_realtime_prune_matches_provider_name_pairs(org):
    """The prune's single exclude() ANDs its two __in lists into a cross-product
    rather than matching (provider, name) pairs, so a stale built-in survives
    whenever its name appears under another provider."""
    upload_models.Command().handle()

    gemini = Provider.objects.get(name="gemini")
    stale = RealtimeModel.objects.create(
        # a real openai catalog name, but under gemini — not a valid pair
        name="gpt-4o-realtime-preview-2024-12-17",
        provider=gemini,
        is_custom=False,
    )

    upload_models.Command().handle()

    assert not RealtimeModel.objects.filter(id=stale.id).exists()


# ---- an empty/unreadable catalog file must never wipe the catalog ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    "uploader_name,model_cls",
    [
        ("upload_llm_models", LLMModel),
        ("upload_embedding_models", EmbeddingModel),
        ("upload_realtime_agent_models", RealtimeModel),
        ("upload_realtime_transcription_models", RealtimeTranscriptionModel),
    ],
)
def test_an_empty_catalog_file_prunes_nothing(monkeypatch, uploader_name, model_cls):
    """`exclude(pk__in=[])` matches nothing, so NOT(nothing) is everything — an
    empty JSON would otherwise delete the whole shared catalog, cascading into
    every tenant's configs via LLMConfig.model."""
    upload_models.Command().handle()
    before = model_cls.objects.filter(org__isnull=True).count()
    assert before > 0, "seeding produced no catalog rows to protect"

    monkeypatch.setattr(upload_models, "load_json_from_file", lambda path: {})
    getattr(upload_models, uploader_name)()

    assert model_cls.objects.filter(org__isnull=True).count() == before
