from tables.graph_collab.protocol import EditorInfo


def build_editor_info(user) -> EditorInfo:
    avatar_url: str | None = None
    avatar = getattr(user, "avatar", None)
    if avatar and avatar.name:
        try:
            avatar_url = avatar.url
        except ValueError:
            avatar_url = None
    return EditorInfo(
        user_id=user.pk,
        display_name=getattr(user, "display_name", None)
        or getattr(user, "email", None),
        avatar_url=avatar_url,
    )
