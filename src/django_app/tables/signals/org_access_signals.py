from django.dispatch import receiver
from rbac.signals import org_access_changed, user_access_changed
from tables.graph_collab.notifications import GraphEditNotifier


@receiver(org_access_changed)
def recheck_org_access(sender, user_id, org_id, **kwargs):
    """Make the user's open editor sockets in this org re-check their rights now."""
    GraphEditNotifier.notify_permission_changed(user_id=user_id, org_id=org_id)


@receiver(user_access_changed)
def recheck_user_access(sender, user_id, **kwargs):
    """Make every open editor socket of the user re-check its rights now."""
    GraphEditNotifier.notify_user_access_changed(user_id=user_id)
