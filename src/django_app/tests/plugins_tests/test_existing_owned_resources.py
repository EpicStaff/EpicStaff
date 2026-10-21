"""Only ownership rows whose resource still exists count; a deleted resource leaves a tombstone."""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from plugins.models import PluginGrant, PluginOwnedResource
from plugins.ownership.existing_owned import existing_owned_resources
from tables.models import Graph, KeyValueTable, StorageFile

pytestmark = [pytest.mark.django_db]


def _own(resource):
    return PluginOwnedResource.objects.create(
        org_id=resource.org_id,
        plugin_identifier="weather",
        content_type=ContentType.objects.get_for_model(type(resource)),
        object_id=resource.pk,
    )


def _file(organization, path):
    return StorageFile.objects.create(org=organization, path=path, name=path.rsplit("/", 1)[-1], item_type="file")


def _existing(organization):
    return set(existing_owned_resources(PluginOwnedResource.objects.filter(org=organization)))


def test_deleted_resources_are_left_out_and_live_and_binned_ones_count(acme):
    live_flow = _own(Graph.objects.create(name="Live", org=acme))
    binned_flow_row = Graph.objects.create(name="Binned", org=acme)
    binned_flow = _own(binned_flow_row)
    purged_flow_row = Graph.objects.create(name="Purged", org=acme)
    purged_flow = _own(purged_flow_row)
    live_file = _own(_file(acme, "live.txt"))
    binned_file_row = _file(acme, "binned.txt")
    binned_file = _own(binned_file_row)
    deleted_file_row = _file(acme, "deleted.txt")
    deleted_file = _own(deleted_file_row)

    binned_flow_row.delete()
    purged_flow_row.delete()
    Graph.all_objects.get(pk=purged_flow_row.pk).purge()
    StorageFile.all_objects.filter(pk=binned_file_row.pk).update(active=False, soft_deleted_at=timezone.now())
    deleted_file_row.delete()

    assert _existing(acme) == {live_flow, binned_flow, live_file, binned_file}
    # The deleted resources' rows are tombstones, never removed by the delete.
    assert PluginOwnedResource.objects.filter(pk__in=[purged_flow.pk, deleted_file.pk]).count() == 2


def test_the_same_id_of_another_model_does_not_keep_a_tombstone_alive(acme):
    flow = Graph.objects.create(name="Gone", org=acme)
    tombstone = _own(flow)
    flow.delete()
    Graph.all_objects.get(pk=flow.pk).purge()
    KeyValueTable.objects.create(id=flow.pk, name="same_id", org=acme)

    assert tombstone not in _existing(acme)


def test_one_statement_for_one_row_or_twenty_of_three_models(acme, beta):
    _own(Graph.objects.create(name="Only", org=acme))
    for index in range(7):
        _own(Graph.objects.create(name=f"Flow {index}", org=beta))
        _own(_file(beta, f"file-{index}.txt"))
    for index in range(6):
        _own(KeyValueTable.objects.create(name=f"table_{index}", org=beta))
    # Django caches content types per process; the first lookup fills the cache.
    _existing(acme)

    def statements(organization):
        with CaptureQueriesContext(connection) as captured:
            count = len(_existing(organization))
        return count, len(captured.captured_queries)

    assert statements(acme) == (1, 1)
    assert statements(beta) == (20, 1)


def test_the_grants_list_counts_only_existing_resources_in_one_subquery(running_plugin, grant_to, acme, beta, django_assert_num_queries):
    plugin = running_plugin()
    acme_grant, beta_grant = grant_to(plugin, acme), grant_to(plugin, beta)
    kept = Graph.objects.create(name="Kept", org=acme)
    binned = Graph.objects.create(name="Binned", org=acme)
    purged = Graph.objects.create(name="Purged", org=acme)
    for resource in (kept, binned, purged):
        PluginOwnedResource.objects.filter(pk=_own(resource).pk).update(grant=acme_grant)
    binned.delete()
    purged.delete()
    Graph.all_objects.get(pk=purged.pk).purge()
    # Django caches content types per process; the first lookup fills the cache.
    _existing(acme)

    with django_assert_num_queries(2):
        counts = {grant.pk: grant.owned_resource_count for grant in PluginGrant.objects.with_admin_details()}

    assert counts == {acme_grant.pk: 2, beta_grant.pk: 0}
