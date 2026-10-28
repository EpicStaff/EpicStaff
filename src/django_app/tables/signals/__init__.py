from django.dispatch import Signal

# Sent after a `bulk_create` of rows that other apps track per row, as
# `send(sender=<model class>, queryset=<the inserted rows>)`. `bulk_create` fires
# no `post_save`, and with `ignore_conflicts=True` it returns no ids, so the
# sender passes a queryset selecting exactly the rows it inserted. Sent right
# after the insert, inside the caller's transaction when there is one, so a
# receiver's writes roll back with the rows.
rows_bulk_created = Signal()
