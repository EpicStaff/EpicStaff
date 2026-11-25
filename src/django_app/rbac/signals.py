import django.dispatch

# Sent after a user's own profile changes (display name, avatar). Receivers get
# `user`. Kept in rbac so the profile surface needs no knowledge of who reacts.
profile_updated = django.dispatch.Signal()

# Sent inside the transaction that removed `user_id`'s membership in `org_id`, so
# apps outside rbac can delete what the user kept in that org. Receivers get
# `user_id` and `org_id`.
member_removed = django.dispatch.Signal()

# Sent inside the transaction that revoked `user_id`'s superadmin role, so apps
# outside rbac can delete what the user kept in orgs they are not a member of.
# Receivers get `user_id`.
superadmin_revoked = django.dispatch.Signal()
