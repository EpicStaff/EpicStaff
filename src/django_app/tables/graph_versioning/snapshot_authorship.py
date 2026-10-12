from collections.abc import Callable

from django.db import transaction
from django.db.models import BooleanField, F, Func, JSONField, QuerySet, TextField, Value
from rbac.models import OrganizationUser

from tables.models import GraphVersion

# Snapshot keys as written by GraphVersioningService.save_version: whether a snapshot
# records the `$user_id` variable, or any user, as a node's author or last editor.
_RECORDS_USER_JSONPATH = (
    "exists($.node_authorship.* ? (@.created_by == $user_id))"
    " || exists($.node_last_edit.* ? (@.edited_by == $user_id))"
)
_RECORDS_ANY_USER_JSONPATH = (
    "exists($.node_authorship.* ? (@.created_by != null))"
    " || exists($.node_last_edit.* ? (@.edited_by != null))"
)
# Versions loaded, and rewritten, per round trip: snapshots hold whole flows.
_SCRUB_BATCH_SIZE = 100


class _SnapshotMatchesJsonpath(Func):
    """Whether a version's snapshot matches a Postgres jsonpath predicate with `variables`."""

    function = "jsonb_path_match"
    output_field = BooleanField()

    def __init__(self, jsonpath: str, variables: dict):
        super().__init__(
            F("snapshot"),
            Func(Value(jsonpath), template="%(expressions)s::jsonpath", output_field=TextField()),
            Value(variables, output_field=JSONField()),
        )


class VersionSnapshotAuthorshipScrubber:
    """Clear users from the authorship that graph version snapshots recorded.

    A snapshot records each node's author (`node_authorship`) and last editor
    (`node_last_edit`). Restoring a version replays them verbatim, so a user who leaves an
    organization, loses the superadmin role while not a member of it, or is deleted, must
    not stay recorded in its snapshots. Times are kept;
    soft-deleted versions, and versions of soft-deleted flows, are included. The versions
    rewritten are locked until the caller's transaction ends, so concurrent scrubs of the
    same version do not overwrite each other. Registered with rbac as a
    `SnapshotAuthorshipScrubber`.
    """

    @transaction.atomic
    def scrub_in_organization(self, user_id: int, org_id: int) -> int:
        """Clear `user_id` from the snapshots of every flow version in `org_id`.

        Returns the number of versions rewritten.
        """
        return self._scrub(
            GraphVersion.all_objects.filter(graph__org_id=org_id),
            _SnapshotMatchesJsonpath(_RECORDS_USER_JSONPATH, {"user_id": user_id}),
            lambda recorded_user_id: recorded_user_id == user_id,
        )

    @transaction.atomic
    def scrub_in_every_organization(self, user_id: int) -> int:
        """Clear `user_id` from the snapshots of every flow version, whatever its organization.

        Returns the number of versions rewritten.
        """
        return self._scrub(
            GraphVersion.all_objects.all(),
            _SnapshotMatchesJsonpath(_RECORDS_USER_JSONPATH, {"user_id": user_id}),
            lambda recorded_user_id: recorded_user_id == user_id,
        )

    @transaction.atomic
    def scrub_outside_memberships(self, user_id: int) -> int:
        """Clear `user_id` from the version snapshots of every org they are not a member of.

        For a superadmin losing the role: as one they may have edited flows of any
        organization. Returns the number of versions rewritten.
        """
        member_org_ids = OrganizationUser.objects.filter(user_id=user_id).values("org_id")
        return self._scrub(
            GraphVersion.all_objects.exclude(graph__org_id__in=member_org_ids),
            _SnapshotMatchesJsonpath(_RECORDS_USER_JSONPATH, {"user_id": user_id}),
            lambda recorded_user_id: recorded_user_id == user_id,
        )

    @transaction.atomic
    def scrub_every_user(self) -> int:
        """Clear every recorded user from the snapshots of every flow version.

        For wiping every user account while keeping organizations and their flows.
        Returns the number of versions rewritten.
        """
        return self._scrub(
            GraphVersion.all_objects.all(),
            _SnapshotMatchesJsonpath(_RECORDS_ANY_USER_JSONPATH, {}),
            lambda recorded_user_id: recorded_user_id is not None,
        )

    def _scrub(
        self,
        versions: QuerySet,
        records_scrubbed_user: _SnapshotMatchesJsonpath,
        is_scrubbed_user: Callable[[int | None], bool],
    ) -> int:
        # The database picks the versions recording a scrubbed user, so snapshots that do
        # not are never loaded; those that do are locked, loaded and rewritten a batch at
        # a time.
        recording = (
            versions.filter(records_scrubbed_user)
            .only("id", "snapshot")
            .select_for_update(of=("self",))
            .order_by("pk")
        )
        scrubbed_count = 0
        batch: list[GraphVersion] = []
        for version in recording.iterator(chunk_size=_SCRUB_BATCH_SIZE):
            if self._scrub_snapshot(version.snapshot, is_scrubbed_user):
                batch.append(version)
            if len(batch) == _SCRUB_BATCH_SIZE:
                scrubbed_count += self._save_snapshots(batch)
                batch = []
        return scrubbed_count + self._save_snapshots(batch)

    @staticmethod
    def _save_snapshots(versions: list[GraphVersion]) -> int:
        # Through the base manager: the default one would skip soft-deleted versions.
        GraphVersion.all_objects.bulk_update(versions, ["snapshot"], batch_size=_SCRUB_BATCH_SIZE)
        return len(versions)

    @staticmethod
    def _scrub_snapshot(snapshot: dict, is_scrubbed_user: Callable[[int | None], bool]) -> bool:
        """Null every recorded user `is_scrubbed_user` accepts, in place; return whether any was."""
        recorded_users = [
            *((entry, "created_by") for entry in (snapshot.get("node_authorship") or {}).values()),
            *((entry, "edited_by") for entry in (snapshot.get("node_last_edit") or {}).values()),
        ]
        changed = False
        for entry, user_key in recorded_users:
            if is_scrubbed_user(entry.get(user_key)):
                entry[user_key] = None
                changed = True
        return changed
