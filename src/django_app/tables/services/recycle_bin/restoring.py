"""Tells a post_save receiver that the save is a recycle-bin restore. Import-free, so signals can use it.

A restore saves the rows that have post_save receivers one by one inside its
transaction. A receiver that calls an outside service (a Telegram setWebhook) must
wait for the commit: a rolled-back restore must call nothing, and an HTTP call must
not hold the restore's row locks.
"""

_RESTORING_ATTRIBUTE = "_restoring_from_recycle_bin"


def mark_restoring(instance) -> None:
    setattr(instance, _RESTORING_ATTRIBUTE, True)


def is_restoring(instance) -> bool:
    return getattr(instance, _RESTORING_ATTRIBUTE, False)
