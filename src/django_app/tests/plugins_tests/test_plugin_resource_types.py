import pytest
from django.db import models

from plugins.manifest import SUPPORTED_BRIDGE_VERSIONS, SUPPORTED_FORMAT_VERSIONS, load_package
from plugins.resource_types import (
    CATALOG_TYPES,
    IMPORTED_ENTITIES,
    PLUGIN_OWNED_TYPES,
    RESOURCE_MODELS,
    PluginResourceType,
)
from plugins.samples.zip_builder import build_sample_zip
from plugins.services.bundle_reader import read_bundle
from tables.import_export.permissions import ENTITY_RESOURCE_MAP
from tables.import_export.registry import entity_registry
from tests.plugins_tests.helpers import upload


@pytest.mark.parametrize("resource_type", list(PluginResourceType))
def test_every_resource_type_maps_to_a_model_and_a_name_column(resource_type):
    resource_model = RESOURCE_MODELS[resource_type]

    assert issubclass(resource_model.model, models.Model)
    field = resource_model.model._meta.get_field(resource_model.display_field)
    assert field.concrete


def test_no_resource_model_is_mapped_without_an_enum_member():
    assert set(RESOURCE_MODELS) == set(PluginResourceType)


@pytest.mark.parametrize("entity_type", sorted(PLUGIN_OWNED_TYPES))
def test_every_owned_import_type_is_importable_and_permission_gated(entity_type):
    """An owned type without a strategy would be dropped; one without a
    resource mapping would be created with no create check."""
    assert entity_registry.has_strategy(entity_type)
    assert entity_type in ENTITY_RESOURCE_MAP
    assert IMPORTED_ENTITIES[entity_type].resource_type in RESOURCE_MODELS


def test_catalog_types_are_never_owned():
    assert not CATALOG_TYPES & PLUGIN_OWNED_TYPES


def test_supported_versions_include_1():
    assert 1 in SUPPORTED_FORMAT_VERSIONS
    assert 1 in SUPPORTED_BRIDGE_VERSIONS


def test_the_shipped_sample_is_a_valid_plugin():
    package = load_package(read_bundle(upload(build_sample_zip())))

    assert package.manifest.id == "chat-bot"
    assert package.ui_entry == "index.html"
    assert package.icon_data_url.startswith("data:image/svg+xml;base64,")
    assert package.secret_name("OPENAI_API_KEY") == "CHAT_BOT__OPENAI_API_KEY"
    assert package.storage_path("files/tone-guide.md") == "plugins/chat-bot/tone-guide.md"
