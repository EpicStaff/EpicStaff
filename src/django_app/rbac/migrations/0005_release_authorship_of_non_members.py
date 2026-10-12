"""Clear authorship that points at users who are no longer members of the row's organization.

Before this release, removing a member only deleted the membership, and revoking a
superadmin cleared nothing, so existing rows can still name a user who has since left
their organization. Authorship is now rendered with the author's name and avatar, so this
applies the release rule once to the data written before it; from here on
`MembershipManagementService.remove_member`, `UserManagementService.revoke_superadmin`
and `UserManagementService.delete_user` keep it applied.

A recorded user is cleared from a row when they have no membership in the row's
organization and are not currently a superadmin (`User.is_superadmin`, whether or not the
account is active). Rows without an organization (shared built-ins) are kept. Cleared are:
the row's `created_by`, the `ResourceLastEdit.edited_by` of the row (the edit time is
kept), and the user ids recorded in flow version snapshots (`node_authorship.*.created_by`,
`node_last_edit.*.edited_by`; times are kept). Soft-deleted rows and versions are included.

Self-contained on purpose: it reads models from the historical app registry only, so later
changes to the live models or the authorship services cannot change what it does.
Irreversible by design: personal data is erased on purpose and there is nothing to restore.
"""

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import migrations
from django.db.models import (
    BooleanField,
    Exists,
    F,
    Func,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    TextField,
    Value,
)

# Every model recording an author holds `created_by` (FK to the user model) and reaches its
# organization through its own `org` FK (OrgScopedModel) or through its flow
# (`graph` FK, AuthorModel graph nodes).
_ORG_LOOKUP_BY_OWNER_FIELD = (("org", "org_id"), ("graph", "graph__org_id"))
# `created_by` there records who issued the key, not the author of an organization resource.
_NOT_AUTHORSHIP = frozenset({("rbac", "apikey")})

_RECORDS_ANY_USER_JSONPATH = (
    "exists($.node_authorship.* ? (@.created_by != null))"
    " || exists($.node_last_edit.* ? (@.edited_by != null))"
)
_SNAPSHOT_BATCH_SIZE = 100


def author_tracked_models(apps) -> list[tuple[type, str]]:
    """Return `(historical model, org lookup)` for every model recording an author.

    Only the model owning the `created_by` column is listed: proxies and multi-table
    children share their parent's column.
    """
    user_model = apps.get_model(settings.AUTH_USER_MODEL)
    tracked = []
    for model in apps.get_models():
        if (model._meta.app_label, model._meta.model_name) in _NOT_AUTHORSHIP:
            continue
        try:
            author_field = model._meta.get_field("created_by")
        except FieldDoesNotExist:
            continue
        if author_field.related_model is not user_model or author_field.model is not model:
            continue
        org_lookup = _org_lookup(model)
        if org_lookup is not None:
            tracked.append((model, org_lookup))
    return tracked


def _org_lookup(model) -> str | None:
    for owner_field_name, org_lookup in _ORG_LOOKUP_BY_OWNER_FIELD:
        try:
            model._meta.get_field(owner_field_name)
        except FieldDoesNotExist:
            continue
        return org_lookup
    return None


def _not_a_member_of(apps, user_column: str, org_column: str) -> Exists:
    """`~Exists` that is true when the user in `user_column` has no membership in `org_column`."""
    organization_user = apps.get_model("rbac", "OrganizationUser")
    return ~Exists(
        organization_user.objects.filter(user_id=OuterRef(user_column), org_id=OuterRef(org_column))
    )


def release_authors(apps) -> int:
    released = 0
    for model, org_lookup in author_tracked_models(apps):
        manager = model._base_manager
        stale = manager.filter(
            Q(**{f"{org_lookup}__isnull": False}),
            created_by__isnull=False,
            created_by__is_superadmin=False,
        ).filter(_not_a_member_of(apps, "created_by_id", org_lookup))
        released += manager.filter(pk__in=stale.values("pk")).update(created_by=None)
    return released


def release_last_edits(apps) -> int:
    content_type_model = apps.get_model("contenttypes", "ContentType")
    resource_last_edit = apps.get_model("rbac", "ResourceLastEdit")
    content_type_id_by_model = {
        (app_label, model_name): content_type_id
        for content_type_id, app_label, model_name in content_type_model.objects.values_list(
            "pk", "app_label", "model"
        )
    }
    released = 0
    # A last edit is only recorded for a model that records an author too.
    for model, org_lookup in author_tracked_models(apps):
        # `object_id` is a bigint: comparing it with a primary key keyed by text
        # (PythonCodeResult) fails in Postgres, and such a model holds no last edits.
        if not _has_integer_primary_key(model):
            continue
        content_type_id = content_type_id_by_model.get(
            (model._meta.app_label, model._meta.model_name)
        )
        if content_type_id is None:
            continue
        resource_org = Subquery(
            model._base_manager.filter(pk=OuterRef("object_id")).values(org_lookup)[:1]
        )
        stale = (
            resource_last_edit.objects.filter(
                content_type_id=content_type_id,
                edited_by__isnull=False,
                edited_by__is_superadmin=False,
            )
            .annotate(resource_org_id=resource_org)
            .filter(resource_org_id__isnull=False)
            .filter(_not_a_member_of(apps, "edited_by_id", "resource_org_id"))
        )
        released += resource_last_edit.objects.filter(pk__in=stale.values("pk")).update(
            edited_by=None
        )
    return released


class _SnapshotRecordsAnyUser(Func):
    function = "jsonb_path_match"
    output_field = BooleanField()

    def __init__(self):
        super().__init__(
            F("snapshot"),
            Func(
                Value(_RECORDS_ANY_USER_JSONPATH),
                template="%(expressions)s::jsonpath",
                output_field=TextField(),
            ),
        )


def scrub_version_snapshots(apps) -> int:
    graph_version = apps.get_model("tables", "GraphVersion")
    recording = (
        graph_version._base_manager.filter(_SnapshotRecordsAnyUser())
        .annotate(flow_org_id=F("graph__org_id"))
        .only("id", "snapshot")
        .select_for_update(of=("self",))
        .order_by("pk")
    )
    scrubbed = 0
    batch = []
    for version in recording.iterator(chunk_size=_SNAPSHOT_BATCH_SIZE):
        batch.append(version)
        if len(batch) == _SNAPSHOT_BATCH_SIZE:
            scrubbed += _scrub_batch(apps, batch)
            batch = []
    return scrubbed + _scrub_batch(apps, batch)


def _recorded_users(snapshot: dict) -> list[tuple[dict, str]]:
    return [
        *((entry, "created_by") for entry in (snapshot.get("node_authorship") or {}).values()),
        *((entry, "edited_by") for entry in (snapshot.get("node_last_edit") or {}).values()),
    ]


def _scrub_batch(apps, versions: list) -> int:
    if not versions:
        return 0
    recorded_user_ids = {
        entry[user_key]
        for version in versions
        for entry, user_key in _recorded_users(version.snapshot)
        if entry.get(user_key) is not None
    }
    memberships = set(
        apps.get_model("rbac", "OrganizationUser")
        .objects.filter(
            user_id__in=recorded_user_ids,
            org_id__in={version.flow_org_id for version in versions},
        )
        .values_list("user_id", "org_id")
    )
    superadmin_ids = set(
        apps.get_model(settings.AUTH_USER_MODEL)
        ._base_manager.filter(pk__in=recorded_user_ids, is_superadmin=True)
        .values_list("pk", flat=True)
    )
    changed = []
    for version in versions:
        was_changed = False
        for entry, user_key in _recorded_users(version.snapshot):
            user_id = entry.get(user_key)
            if (
                user_id is not None
                and user_id not in superadmin_ids
                and (user_id, version.flow_org_id) not in memberships
            ):
                entry[user_key] = None
                was_changed = True
        if was_changed:
            changed.append(version)
    apps.get_model("tables", "GraphVersion")._base_manager.bulk_update(
        changed, ["snapshot"], batch_size=_SNAPSHOT_BATCH_SIZE
    )
    return len(changed)


def _has_integer_primary_key(model) -> bool:
    primary_key = model._meta.pk
    return isinstance(getattr(primary_key, "target_field", primary_key), IntegerField)


def release_authorship_of_non_members(apps, schema_editor):
    from loguru import logger

    released_authors = release_authors(apps)
    released_last_edits = release_last_edits(apps)
    scrubbed_versions = scrub_version_snapshots(apps)
    # The only record of what this irreversible erasure did.
    logger.info(
        "Released authorship of non-members: authors={authors} last_edits={last_edits} "
        "versions={versions}",
        authors=released_authors,
        last_edits=released_last_edits,
        versions=scrubbed_versions,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0011_agentdefinition_created_at"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("rbac", "0004_resource_last_edit"),
        ("tables", "0261_created_at_on_realtime_provider_configs"),
    ]

    operations = [
        migrations.RunPython(
            release_authorship_of_non_members,
            # Irreversible by design: the cleared personal data is gone on purpose.
            reverse_code=migrations.RunPython.noop,
        ),
    ]
