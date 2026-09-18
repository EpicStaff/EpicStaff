from django.db import transaction

from tables.models import GraphVersion


def bulk_delete_graph_versions(ids, org_id, dry_run=False):
    """GraphVersion has zero referencing sources anywhere in the schema
    (nothing holds an FK to it -- Graph has no current_version pointer, and
    restore/create_graph read a version's snapshot at call time without
    retaining a reference back to it), so there is nothing an
    in_use_restricted guard could ever block. Unlike every other entity in
    this rollout, the response has no `skipped_ids`/`usage` keys -- both
    would be permanently empty here (nothing to skip, nothing to report),
    so they're omitted rather than shipped as dead, always-vacuous fields.
    """
    found = list(GraphVersion.objects.filter(graph__org_id=org_id, id__in=ids))
    found_ids = {version.id for version in found}
    not_found_ids = [i for i in ids if i not in found_ids]

    deleted_ids = []
    with transaction.atomic():
        for version in found:
            version_id = version.id  # capture before delete() nulls instance.pk
            if not dry_run:
                version.delete()
            deleted_ids.append(version_id)

    return {
        "dry_run": dry_run,
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "not_found_ids": not_found_ids,
    }
