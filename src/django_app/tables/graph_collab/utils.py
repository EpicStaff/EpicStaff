from rbac.access.principals import is_pinned_org_principal

from tables.graph_collab.protocol import EditorInfo


def build_editor_info(user) -> EditorInfo:
    # A pinned principal is no user: it has no id to match against an editor,
    # so it is shown by name only and never mistaken for a person.
    if is_pinned_org_principal(user):
        return EditorInfo(user_id=None, display_name=user.display_name, avatar_url=None)
    avatar_url: str | None = None
    avatar = getattr(user, "avatar", None)
    if avatar and avatar.name:
        try:
            avatar_url = avatar.url
        except ValueError:
            avatar_url = None
    return EditorInfo(
        user_id=user.pk,
        display_name=getattr(user, "display_name", None) or getattr(user, "email", None),
        avatar_url=avatar_url,
    )
