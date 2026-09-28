from django.dispatch import receiver
from rbac.signals import profile_updated
from tables.graph_collab.notifications import GraphEditNotifier


@receiver(profile_updated)
def broadcast_profile_updated(sender, user, **kwargs):
    """Refresh the editor's presence card in every graph they are editing."""
    GraphEditNotifier.notify_profile_updated(user)
