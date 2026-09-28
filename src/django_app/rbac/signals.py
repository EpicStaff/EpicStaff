import django.dispatch

# Sent after a user's own profile changes (display name, avatar). Receivers get
# `user`. Kept in rbac so the profile surface needs no knowledge of who reacts.
profile_updated = django.dispatch.Signal()
