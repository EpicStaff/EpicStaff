import threading

from django.db import transaction
from django.db.models.signals import post_delete

from tables.services.python_code_cleanup_service import PythonCodeCleanupService

_state = threading.local()


# Registration of the on_commit callback is unconditional on every _buffer() call,
# not gated behind "pending is None". A transaction rollback discards Django's
# on_commit registration, but it does NOT reset our threading.local state — so if we
# only registered _flush once per "pending is None" transition, a rollback after
# pending was populated would leave pending permanently non-empty and _flush
# permanently un-registered for the rest of this thread's lifetime (a real risk for
# WSGI/ASGI workers that reuse threads across requests). Re-registering on every call
# makes the mechanism self-healing after a rollback, at the cost of a few redundant
# on_commit registrations within the same transaction (harmless — _flush is idempotent
# below).
def _buffer(python_code_ids) -> None:
    pending = getattr(_state, "pending", None)
    if pending is None:
        pending = _state.pending = set()
    pending.update(python_code_ids)
    transaction.on_commit(_flush)


def _flush() -> None:
    pending = getattr(_state, "pending", None)
    if not pending:
        return
    _state.pending = None
    PythonCodeCleanupService.delete_orphaned(pending)


def _collect_owned_python_code(sender, instance, **kwargs):
    field_names = PythonCodeCleanupService.owner_fields_by_model().get(sender)
    if not field_names:
        return
    _buffer({getattr(instance, name) for name in field_names})


for owner_model in PythonCodeCleanupService.owner_fields_by_model():
    post_delete.connect(
        _collect_owned_python_code,
        sender=owner_model,
        dispatch_uid=f"delete_owned_python_code_{owner_model._meta.label_lower}",
    )
