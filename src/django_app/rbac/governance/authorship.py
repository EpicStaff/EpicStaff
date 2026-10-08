from collections.abc import Callable

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.db import models, transaction
from django.db.models import BooleanField, F, Func, JSONField, Q, QuerySet, TextField, Value
from tables.models import GraphVersion

from rbac.authorship.checks import MISSING_ORG_LOOKUP_CHECK_ID
from rbac.authorship.registry import author_tracked_models, last_edit_tracked_models
from rbac.models import OrganizationUser, ResourceLastEdit


class AuthorshipReleaseService:
    """Clear the authorship and last-editor records a user holds on organization resources."""

    def release(self, user_id: int, org_id: int) -> int:
        """Clear `user_id` as author and as last editor of every row in `org_id`.

        Last edits keep their time. Soft-deleted rows are included. Returns the number of
        author and last-edit rows released.
        """
        return self._release_matching(user_id, lambda lookup: Q(**{lookup: org_id}))

    def release_outside_memberships(self, user_id: int) -> int:
        """Clear the user as author and last editor in every org they are not a member of.

        Rows without an organization are kept, soft-deleted rows are included. Returns
        the number of author and last-edit rows released.
        """
        member_org_ids = OrganizationUser.objects.filter(user_id=user_id).values("org_id")
        return self._release_matching(
            user_id,
            lambda lookup: (
                Q(**{f"{lookup}__isnull": False}) & ~Q(**{f"{lookup}__in": member_org_ids})
            ),
        )

    def _release_matching(self, user_id: int, org_condition: Callable[[str], Q]) -> int:
        released = 0
        for model, org_lookup in self._tracked_models():
            released += (
                model._base_manager.filter(org_condition(org_lookup))
                .filter(created_by_id=user_id)
                .update(created_by=None)
            )
        return released + self._release_last_edits(user_id, org_condition)

    @staticmethod
    def _release_last_edits(user_id: int, org_condition: Callable[[str], Q]) -> int:
        released_resources = Q()
        for model, org_lookup in last_edit_tracked_models():
            released_resources |= Q(
                content_type=ContentType.objects.get_for_model(model),
                object_id__in=model._base_manager.filter(org_condition(org_lookup)).values("pk"),
            )
        return ResourceLastEdit.objects.filter(released_resources, edited_by_id=user_id).update(
            edited_by=None
        )

    @staticmethod
    def _tracked_models() -> list[tuple[type[models.Model], str]]:
        # The system check reports this at startup; failing before any update keeps
        # a misconfigured deployment from releasing only part of the rows.
        tracked = author_tracked_models()
        misconfigured = [model.__name__ for model, org_lookup in tracked if org_lookup is None]
        if misconfigured:
            raise ImproperlyConfigured(
                f"AuthorModel subclasses without author_org_lookup: {', '.join(misconfigured)} "
                f"(system check {MISSING_ORG_LOOKUP_CHECK_ID})."
            )
        return tracked


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
    organization, or is deleted, must not stay recorded in its snapshots. Times are kept;
    soft-deleted versions, and versions of soft-deleted flows, are included. The versions
    rewritten are locked until the caller's transaction ends, so concurrent scrubs of the
    same version do not overwrite each other.
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
