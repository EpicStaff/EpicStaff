from rbac.profile.avatar import build_avatar_url

from tables.graph_collab.protocol import EditorInfo


def build_editor_info(user) -> EditorInfo:
    # Tolerates user stand-ins without an `avatar` attribute.
    avatar_url = build_avatar_url(user) if getattr(user, "avatar", None) else None
    return EditorInfo(
        user_id=user.pk,
        display_name=getattr(user, "display_name", None) or getattr(user, "email", None),
        avatar_url=avatar_url,
    )
