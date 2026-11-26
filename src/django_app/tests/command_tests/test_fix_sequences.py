"""`fix_sequences`, run at every start: a sequence catches up with its table, never goes back."""

import pytest
from ai_models.models import LLMModel
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from plugins.models import PluginOwnedResource
from plugins.ownership.existing_owned import existing_owned_resources

pytestmark = [pytest.mark.django_db]


def _llm_model(organization, name, **fields):
    return LLMModel.objects.create(org=organization, name=name, **fields)


def test_a_row_inserted_with_an_id_past_the_sequence_is_never_collided_with(default_org):
    ahead = _llm_model(default_org, "restored", id=_llm_model(default_org, "probe").pk + 1000)

    call_command("fix_sequences")

    assert _llm_model(default_org, "next").pk > ahead.pk


def test_the_id_of_a_deleted_row_is_never_handed_out_again(default_org):
    call_command("fix_sequences")
    deleted = _llm_model(default_org, "deleted")
    deleted_id = deleted.pk
    deleted.delete()

    call_command("fix_sequences")

    assert _llm_model(default_org, "new").pk > deleted_id


def test_a_restart_never_makes_a_new_row_the_plugin_s_deleted_one(default_org):
    """A plugin's ownership row outlives its deleted resource until the hourly sweep; a new row
    given that id would be the plugin's: its purge would delete it."""
    call_command("fix_sequences")
    plugin_model = _llm_model(default_org, "plugin's model")
    PluginOwnedResource.objects.create(
        org=default_org,
        plugin_identifier="weather",
        content_type=ContentType.objects.get_for_model(LLMModel),
        object_id=plugin_model.pk,
    )
    plugin_model.delete()

    call_command("fix_sequences")
    _llm_model(default_org, "the organization's model")

    assert not existing_owned_resources(PluginOwnedResource.objects.filter(org=default_org)).exists()
