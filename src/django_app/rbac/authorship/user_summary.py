from collections.abc import Iterable

from django.contrib.auth import get_user_model
from rest_framework import serializers

from rbac.profile.avatar import build_avatar_url

# The only user columns an authorship summary reads; anything else (email, roles,
# memberships, is_active) never leaves the server through `created_by`/`last_edited_by`.
USER_SUMMARY_FIELDS = ("id", "display_name", "avatar")


def represent_user_summary(user, request) -> dict | None:
    """Render `user` the way every API response renders an author or last editor.

    Returns None for no user. `avatar_url` is absolute when `request` is given.
    """
    if user is None:
        return None
    return {
        "id": user.pk,
        "display_name": user.display_name or None,
        "avatar_url": build_avatar_url(user, request),
    }


def user_summaries_by_id(user_ids: Iterable[int | None], request) -> dict[int, dict]:
    """Load the users behind `user_ids` in one query and render each as a summary.

    None ids are ignored; ids of deleted users are absent from the result.
    """
    wanted_ids = {user_id for user_id in user_ids if user_id is not None}
    if not wanted_ids:
        return {}
    users = get_user_model().objects.filter(pk__in=wanted_ids).only(*USER_SUMMARY_FIELDS)
    return {user.pk: represent_user_summary(user, request) for user in users}


class UserSummarySerializer(serializers.Serializer):
    """Read-only public identity of a user: id, display name and avatar URL."""

    id = serializers.IntegerField(read_only=True)
    display_name = serializers.CharField(read_only=True, allow_null=True)
    avatar_url = serializers.CharField(read_only=True, allow_null=True)

    def to_representation(self, instance):
        return represent_user_summary(instance, self.context.get("request"))
