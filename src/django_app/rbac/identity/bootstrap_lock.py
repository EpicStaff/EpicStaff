from django.db import connection

# Arbitrary but stable. Every writer that creates the bootstrap superadmin
# takes this one key, so the "does any user exist yet?" check cannot
# interleave with another writer's insert.
BOOTSTRAP_LOCK_KEY = 918_273_645


def acquire_bootstrap_lock() -> None:
    """Serialize bootstrap superadmin creation across connections.

    Must be called inside ``transaction.atomic()``: ``pg_advisory_xact_lock``
    is scoped to the transaction and released automatically on commit or
    rollback, so there is no unlock path to leak. The second caller blocks
    here until the first commits, then observes the user it created and
    raises ``SetupAlreadyCompletedError``.

    No-op on non-PostgreSQL backends, which have no equivalent primitive.
    Production and the test database are both PostgreSQL.

    Raises:
        RuntimeError: if called outside ``transaction.atomic()``, where the
            lock would be taken and released immediately, silently providing
            zero serialization.
    """
    if not connection.in_atomic_block:
        raise RuntimeError(
            "acquire_bootstrap_lock() must be called inside "
            "transaction.atomic(); outside one, pg_advisory_xact_lock is "
            "released immediately and provides no serialization."
        )
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [BOOTSTRAP_LOCK_KEY])
