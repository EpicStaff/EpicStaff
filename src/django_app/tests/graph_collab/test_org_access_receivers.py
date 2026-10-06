"""The tables receivers forward rbac's access signals to GraphEditNotifier."""

from rbac.signals import org_access_changed, user_access_changed


def test_org_access_changed_notifies_the_org_group(mocker):
    notify = mocker.patch(
        "tables.signals.org_access_signals.GraphEditNotifier.notify_permission_changed"
    )

    org_access_changed.send(sender=object, user_id=3, org_id=9)

    notify.assert_called_once_with(user_id=3, org_id=9)


def test_user_access_changed_notifies_the_user_group(mocker):
    notify = mocker.patch(
        "tables.signals.org_access_signals.GraphEditNotifier.notify_user_access_changed"
    )

    user_access_changed.send(sender=object, user_id=3)

    notify.assert_called_once_with(user_id=3)
