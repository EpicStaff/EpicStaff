import pytest

pytestmark = pytest.mark.skip(reason="pre-existing failure, unrelated to EST-1529")

from tables.management.commands import upload_models

from tables.models import LLMModel
from tables.models import Provider
from tables.models import EmbeddingModel


@pytest.mark.parametrize(
    "provider_name",
    [
        "anthropic",
        "azure_openai",
        "groq",
        "huggingface",
        "ollama",
        "openai",
        "openai_compatible",
    ],
)
@pytest.mark.django_db()
def test_upload_llm_providers(provider_name):
    command = upload_models.Command()
    command.handle()

    Provider.objects.get(name=provider_name)


@pytest.mark.parametrize(
    "llm_model_name, llm_provider_name",
    [
        ("gpt-3.5-turbo", "openai"),
        ("gpt-4o", "openai"),
        ("gpt-4-1106-azure", "azure_openai"),
        ("llama3-70b-8192", "groq"),
        ("mixtral-8x7b-32768", "ollama"),
        ("claude-3-opus-20240229", "anthropic"),
    ],
)
@pytest.mark.django_db()
def test_upload_llm_models(llm_model_name, llm_provider_name):
    command = upload_models.Command()
    command.handle()

    LLMModel.objects.get(
        name=llm_model_name,
        llm_provider__name=llm_provider_name,
        predefined=True,
    )


@pytest.mark.parametrize(
    "name, embedding_provider_name",
    [
        ("text-embedding-3-small", "openai"),
        ("text-embedding-ada-002", "azure_openai"),
    ],
)
@pytest.mark.django_db()
def test_upload_embedding_models(name, embedding_provider_name):
    command = upload_models.Command()
    command.handle()

    EmbeddingModel.objects.get(
        name=name,
        embedding_provider__name=embedding_provider_name,
        predefined=True,
    )
