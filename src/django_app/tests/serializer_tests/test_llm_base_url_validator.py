"""`validate_llm_base_url` blocks only cloud-metadata hosts on base_url.

A backend LLM/embedding/realtime call must not be aimable at the link-local
metadata range (169.254.0.0/16) or Azure's WireServer (168.63.129.16), while a
public endpoint and a LAN address (self-hosted Ollama/vLLM) stay allowed.
"""

import pytest
from rest_framework import serializers

from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import LLMModel
from tables.serializers.model_serializers.embedding_serializers import EmbeddingModelSerializer
from tables.serializers.model_serializers.llm_serializers import (
    LLMConfigSerializer,
    LLMModelSerializer,
)
from tables.serializers.model_serializers.realtime_serializers import (
    OpenAIRealtimeConfigSerializer,
)
from tables.validators.llm_base_url_validator import validate_llm_base_url

REJECTED_URLS = [
    "http://169.254.169.254/latest/meta-data/",
    "http://169.254.169.254:80/",
    "https://169.254.0.1/",
    "http://168.63.129.16/metadata/instance",
    "169.254.169.254",  # no scheme -- still a metadata IP
    "169.254.169.254:8000",
    # Non-canonical IPv4 encodings the outbound resolver still reaches 169.254.169.254 by.
    "http://2852039166/",  # decimal integer
    "http://0xa9fea9fe/",  # hex
    "http://0251.0376.0251.0376/",  # octal
    "http://[::ffff:169.254.169.254]/",  # IPv4-mapped IPv6
]

ACCEPTED_URLS = [
    "https://api.openai.com/v1",
    "http://192.168.1.10:11434",  # LAN Ollama -- intentionally allowed
    "http://10.0.0.5:8000/v1",  # LAN vLLM -- intentionally allowed
    "http://ollama:11434",  # hostname -- not resolved here by design
    "https://metadata.example.com/",  # hostname that merely contains "metadata"
    "",
    None,
]


class TestValidateLlmBaseUrl:
    @pytest.mark.parametrize("url", REJECTED_URLS)
    def test_rejects_metadata_hosts(self, url):
        with pytest.raises(serializers.ValidationError):
            validate_llm_base_url(url)

    @pytest.mark.parametrize("url", ACCEPTED_URLS)
    def test_accepts_public_lan_and_hostname_urls(self, url):
        assert validate_llm_base_url(url) is None


@pytest.mark.django_db
class TestBaseUrlSerializerWiring:
    def test_llm_model_rejects_metadata_base_url(self, openai_provider):
        serializer = LLMModelSerializer(
            data={
                "name": "m",
                "llm_provider": openai_provider.pk,
                "base_url": "http://169.254.169.254/latest/meta-data/",
            }
        )
        assert not serializer.is_valid()
        assert "base_url" in serializer.errors

    def test_llm_model_accepts_lan_base_url(self, openai_provider):
        serializer = LLMModelSerializer(
            data={
                "name": "m",
                "llm_provider": openai_provider.pk,
                "base_url": "http://192.168.1.10:11434",
            }
        )
        assert serializer.is_valid(), serializer.errors

    def test_embedding_model_rejects_metadata_base_url(self, openai_provider):
        serializer = EmbeddingModelSerializer(
            data={
                "name": "e",
                "embedding_provider": openai_provider.pk,
                "base_url": "http://168.63.129.16/metadata",
            }
        )
        assert not serializer.is_valid()
        assert "base_url" in serializer.errors

    def test_embedding_model_accepts_public_base_url(self, openai_provider):
        serializer = EmbeddingModelSerializer(
            data={
                "name": "e",
                "embedding_provider": openai_provider.pk,
                "base_url": "https://api.openai.com/v1",
            }
        )
        assert serializer.is_valid(), serializer.errors

    def test_llm_config_rejects_metadata_base_url(self):
        serializer = LLMConfigSerializer(
            data={"custom_name": "cfg", "base_url": "http://2852039166/"}
        )
        assert not serializer.is_valid()
        assert "base_url" in serializer.errors

    def test_llm_config_accepts_lan_base_url(self):
        serializer = LLMConfigSerializer(
            data={"custom_name": "cfg", "base_url": "http://192.168.1.10:11434"}
        )
        assert serializer.is_valid(), serializer.errors

    def test_openai_realtime_config_rejects_metadata_base_url(self):
        serializer = OpenAIRealtimeConfigSerializer(
            data={
                "custom_name": "cfg",
                "model_name": "gpt-realtime-1.5",
                "base_url": "http://169.254.169.254/",
            }
        )
        assert not serializer.is_valid()
        assert "base_url" in serializer.errors
