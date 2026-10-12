from rbac.authorship.last_edit import LastEditTracker


class LastEditDestroyViewSetMixin:
    """Record a deleted row's owner (a node's or edge's graph) as edited by the acting user.

    Put it after the org-scoping mixin in a ModelViewSet's bases.
    """

    def perform_destroy(self, instance):
        tracker = LastEditTracker(self.request.user)
        tracker.watch_delete(instance)
        super().perform_destroy(instance)
        tracker.finish()
