def expected_user_summary(user) -> dict:
    """The `created_by` / `last_edited_by` object an API response shows for an avatar-less user."""
    return {"id": user.id, "display_name": user.display_name, "avatar_url": None}
