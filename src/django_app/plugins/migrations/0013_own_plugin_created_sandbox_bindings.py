"""Record the venvs and custom libraries plugins created before they were ownable as theirs.

A binding a plugin's service account creates has been recorded as the plugin's since the
bindings became ownable; the ones created earlier have no ownership row, so a suspension does
not cover them and deleting the plugin's data leaves them behind.

Nothing on a binding names the plugin: its `created_by` is empty, as for the system API key's
bindings or a person's whose user is gone. What names it is the plugin's activity event for
the create request, which is kept for good. Such an event names no row (a create's URL holds no
id, and the binding was not yet one of the rows an event takes its target from), only the
organization and the time, and it is written right after the response, a few milliseconds
after the binding. So an event claims the binding created before it, within `MATCH_WINDOW`
and after the organization's previous plugin create event of the same kind, when there is
exactly one; a plugin's creates one after another each claim their own. When two creates
overlapped, or another binding without an author was created in between, the event is left
alone and only counted in the log: wrongly claiming a binding would let a purge delete the
organization's own venv. One false claim stays possible: when the binding the plugin created
was deleted since, a binding without an author that the organization created within the
window before the event is the only candidate left, and is claimed.

Claimed only under a grant of the plugin in the binding's organization that existed when the
event was written, so a later plugin reusing the identifier never inherits an earlier one's
bindings. A binding a person created (`created_by` set) or one already owned is never claimed.
Idempotent; reverting removes nothing, as the rows are what the code expects anyway.

The rules are copied here rather than imported: a migration must keep doing what it did when
it was written, whatever the app code turns into later.
"""

import bisect
from datetime import timedelta

from django.db import migrations
from django.db.models import Exists, OuterRef
from loguru import logger

# Between the binding's insert and the event's, the request makes no network call: the
# commit, the user audit record's two queries, the response's rendering and the event's own
# insert, all in one process and on one clock, so tens of milliseconds. Two seconds still
# covers a stalled database, and keeps the window in which another binding can be wrongly
# claimed small.
MATCH_WINDOW = timedelta(seconds=2)
BATCH_SIZE = 1000
# The route of each binding model's create request, as the activity event records it.
CREATE_ROUTES = {
    "SandboxVenvBinding": "api/venvs/",
    "SandboxCustomLibraryBinding": "api/custom-libraries/",
}


def own_plugin_created_bindings(apps, schema_editor):
    for model_name, route in CREATE_ROUTES.items():
        _own_bindings(apps, apps.get_model("proxies", model_name), route)


def _own_bindings(apps, binding_model, route):
    PluginActivityEvent = apps.get_model("plugins", "PluginActivityEvent")
    PluginOwnedResource = apps.get_model("plugins", "PluginOwnedResource")
    PluginGrant = apps.get_model("plugins", "PluginGrant")
    ContentType = apps.get_model("contenttypes", "ContentType")

    events = list(
        PluginActivityEvent.objects.filter(
            action="api_request",
            actor_kind="plugin",
            request_method="POST",
            request_route=route,
            response_status=201,
            target_id__isnull=True,
            organization_id__isnull=False,
        )
        .order_by("created_at", "pk")
        .only("pk", "plugin_identifier", "organization_id", "on_behalf_of_user", "created_at")
    )
    if not events:
        return
    content_type = ContentType.objects.get_for_model(binding_model)
    unowned_bindings = (
        binding_model._base_manager.filter(
            created_by__isnull=True,
            org_id__in={event.organization_id for event in events},
        )
        .filter(
            ~Exists(
                PluginOwnedResource.objects.filter(
                    content_type_id=content_type.pk, object_id=OuterRef("pk")
                )
            )
        )
        .order_by("created_at", "pk")
        .values_list("pk", "org_id", "created_at")
    )
    bindings_by_org: dict[int, list[tuple]] = {}
    for pk, org_id, created_at in unowned_bindings:
        bindings_by_org.setdefault(org_id, []).append((created_at, pk))

    grants = {
        (identifier, org_id): (grant_id, granted_at)
        for grant_id, identifier, org_id, granted_at in PluginGrant.objects.filter(
            org_id__in=bindings_by_org
        ).values_list("pk", "plugin__identifier", "org_id", "created_at")
    }
    previous_event_at = {}
    owned = []
    ambiguous = 0
    for event in events:
        org_id = event.organization_id
        # A binding created before the organization's previous create event of this kind
        # belongs to that request, not to this one.
        earliest = event.created_at - MATCH_WINDOW
        if org_id in previous_event_at:
            earliest = max(earliest, previous_event_at[org_id])
        previous_event_at[org_id] = event.created_at
        bindings = bindings_by_org.get(org_id, [])
        start = bisect.bisect_right(bindings, (earliest, float("inf")))
        end = bisect.bisect_right(bindings, (event.created_at, float("inf")))
        candidates = [pk for _, pk in bindings[start:end]]
        if len(candidates) > 1:
            ambiguous += 1
        if len(candidates) != 1:
            continue
        grant_id, granted_at = grants.get((event.plugin_identifier, org_id), (None, None))
        if grant_id is None or granted_at > event.created_at:
            continue
        owned.append(
            PluginOwnedResource(
                org_id=org_id,
                grant_id=grant_id,
                plugin_identifier=event.plugin_identifier,
                content_type_id=content_type.pk,
                object_id=candidates[0],
                on_behalf_of_id=event.on_behalf_of_user_id,
            )
        )
    PluginOwnedResource.objects.bulk_create(owned, batch_size=BATCH_SIZE, ignore_conflicts=True)
    if owned or ambiguous:
        logger.info(
            "{}: recorded {} binding(s) as their plugin's; {} create event(s) matched more"
            " than one binding, so those stay unowned",
            binding_model._meta.label,
            len(owned),
            ambiguous,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("plugins", "0012_reencrypt_plugin_secrets_master_key"),
        ("proxies", "0004_scope_sandbox_resources"),
    ]

    operations = [
        migrations.RunPython(own_plugin_created_bindings, migrations.RunPython.noop),
    ]
