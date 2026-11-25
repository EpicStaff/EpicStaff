from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection
from loguru import logger

AUTO_FIELD_TYPES = ("AutoField", "BigAutoField", "SmallAutoField")


class Command(BaseCommand):
    """Move each table's id sequence up past the highest id the table holds.

    Rows inserted with explicit ids (a restored dump, a migration or fixture that names its
    ids) leave the sequence behind, and the next insert would collide with one of them.

    A sequence is only ever moved forward, never back to the highest id still in the table:
    an id is handed out once. Rows that point at a deleted row by id alone rely on that (a
    plugin's ownership row stays behind its deleted resource until a sweep removes it), and a
    new row given the deleted row's id would be taken for it.
    """

    help = "Move every table's id sequence up past the highest id in the table."

    def handle(self, *args, **options):
        moved_count = 0
        with connection.cursor() as cursor:
            for model in apps.get_models():
                meta = model._meta
                if not meta.pk or meta.pk.attname != "id":
                    continue
                if meta.pk.get_internal_type() not in AUTO_FIELD_TYPES:
                    continue
                try:
                    if _move_sequence_forward(cursor, meta.db_table):
                        moved_count += 1
                except DatabaseError:
                    # A model whose table or sequence this database does not have.
                    continue

        if moved_count:
            logger.success("Moved the id sequences of {} tables forward", moved_count)
        else:
            logger.info("No id sequence was behind its table")


def _move_sequence_forward(cursor, table: str) -> bool:
    """Set the table's id sequence to its highest id when the sequence has not reached it.

    Returns:
        Whether the sequence was moved.
    """
    cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", [connection.ops.quote_name(table)])
    sequence = cursor.fetchone()[0]
    if sequence is None:
        return False
    # Postgres returns the sequence's name already quoted where it needs to be.
    cursor.execute(f"SELECT last_value, is_called FROM {sequence}")
    last_value, is_called = cursor.fetchone()
    highest_handed_out = last_value if is_called else last_value - 1
    cursor.execute(f"SELECT MAX(id) FROM {connection.ops.quote_name(table)}")
    highest_id = cursor.fetchone()[0]
    if highest_id is None or highest_id <= highest_handed_out:
        return False
    cursor.execute("SELECT setval(%s::regclass, %s)", [sequence, highest_id])
    return True
