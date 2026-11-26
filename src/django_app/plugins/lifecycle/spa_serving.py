"""Taking a plugin's published frontend out of service, and putting it back, after commit.

nginx serves a plugin host's SPA paths only through the plugin's `current` link, so a plugin
out of service (uninstalled, or being deleted) loses the link and its host answers 404 on
every one of them. Its version directories stay, for a reinstall; deleting the plugin removes
them. Each write runs once the transaction commits and is robust: a failure is logged, the
lifecycle change stands, and `SpaStateReconciler` repairs the link on its next pass.

The writes are not ordered against each other: callbacks of an uninstall and a reinstall
that commit at nearly the same time may run in the other order, leaving the link as the
earlier change wanted. `SpaStateReconciler` repairs that too, on its next pass, from the
plugin's state in the database.
"""

from django.db import transaction

from plugins.packages.spa_publisher import SpaPublisher


def withdraw_spa_on_commit(identifier: str) -> None:
    """Serve none of the plugin's SPA paths once the current transaction commits."""

    # A named function, not a `partial`: Django logs a failed robust callback by its
    # `__qualname__`, which a `partial` lacks.
    def withdraw_spa() -> None:
        SpaPublisher().remove_current(identifier)

    transaction.on_commit(withdraw_spa, robust=True)


def serve_spa_on_commit(identifier: str, version: str) -> None:
    """Serve `version`'s published files once the current transaction commits."""

    def serve_spa() -> None:
        SpaPublisher().switch_current(identifier, version)

    transaction.on_commit(serve_spa, robust=True)
