"""The record of a plugin's own database: created at approval, with names, an installation id and a
password only the node gets."""

import re

import pytest
from django.db.models import ProtectedError
from plugins.databases.database_records import app_password_of
from plugins.models import Plugin, PluginDatabase, PluginDatabaseState, PluginState, ReviewState
from src.shared.models.plugin_nodes import database_names_for

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.package_builder import backend_manifest, build_package

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]


def test_approving_a_package_with_a_database_creates_its_record(database_plugin, plugin_database_server):
    plugin = database_plugin()

    record = PluginDatabase.objects.get()
    assert record.plugin == plugin
    assert record.server == plugin_database_server
    assert (record.database_name, record.owner_role, record.app_role, record.job_role) == (
        "plugin_weather",
        "weather_owner",
        "weather_app",
        "weather_job",
    )
    assert record.state == PluginDatabaseState.PENDING
    assert record.applied_migrations == []
    assert plugin.state == PluginState.PROVISIONING


def test_a_dash_in_the_identifier_becomes_an_underscore_in_every_name(database_plugin):
    database_plugin(id="my-plugin")

    record = PluginDatabase.objects.get()
    assert (record.database_name, record.owner_role, record.app_role, record.job_role) == (
        "plugin_my_plugin",
        "my_plugin_owner",
        "my_plugin_app",
        "my_plugin_job",
    )


def test_the_names_are_the_ones_the_node_derives(database_plugin):
    plugin = database_plugin()

    record = PluginDatabase.objects.get()
    names = database_names_for(plugin.identifier)
    assert (record.database_name, record.owner_role, record.app_role, record.job_role) == (
        names.database,
        names.owner_role,
        names.app_role,
        names.job_role,
    )


def test_the_app_password_is_stored_only_encrypted(database_plugin):
    database_plugin()

    record = PluginDatabase.objects.get()
    password = app_password_of(record)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", password)
    stored_text = [
        str(getattr(record, field.attname))
        for field in PluginDatabase._meta.concrete_fields
        if field.name != "app_password_encrypted"
    ]
    assert all(password not in text for text in stored_text)
    assert password not in record.app_password_encrypted


def test_each_installation_gets_its_own_id_and_password(database_plugin):
    database_plugin()
    database_plugin(id="forecast")

    first, second = PluginDatabase.objects.order_by("pk")
    for record in (first, second):
        assert re.fullmatch(r"[0-9a-f]{32}", record.installation_id)
    assert first.installation_id != second.installation_id
    assert app_password_of(first) != app_password_of(second)


def test_a_package_without_a_database_gets_no_record(backend_plugin, plugin_database_server):
    backend_plugin()

    assert not PluginDatabase.objects.exists()


def test_without_a_database_server_the_approval_is_refused_and_nothing_is_approved(
    installation, superadmin, plugin_node, superadmin_client
):
    data = build_package(manifest=backend_manifest(database={}))
    package = installation.upload(upload_file(data), len(data), superadmin)

    response = superadmin_client.post(
        f"/api/admin/plugins/packages/{package.pk}/approve/", {"untrusted_acknowledged": True}, format="json"
    )

    assert (response.status_code, response.json()["code"]) == (409, "no_plugin_database_server")
    package.refresh_from_db()
    assert package.review_state == ReviewState.PENDING
    plugin = Plugin.objects.get()
    assert (plugin.current_package_id, plugin.state) == (None, PluginState.UPLOADED)
    assert not hasattr(plugin, "placement")
    assert not PluginDatabase.objects.exists()


def test_a_plugin_whose_database_has_a_record_cannot_be_deleted(database_plugin):
    plugin = database_plugin()

    with pytest.raises(ProtectedError):
        plugin.delete()

    assert PluginDatabase.objects.filter(plugin=plugin).exists()


def test_the_record_is_created_once(database_plugin, plugin_database_server):
    from plugins.databases.database_records import PluginDatabaseRecords

    plugin = database_plugin()
    record = PluginDatabase.objects.get()

    assert PluginDatabaseRecords().ensure_for(plugin) == record
    assert PluginDatabase.objects.count() == 1
