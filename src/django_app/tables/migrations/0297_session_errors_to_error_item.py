"""Store every saved session error as an error item {code, detail, attr, context}.

Crew now writes a node's error card as `message_data.error` and a failed session's
status as `status_data.error`, both an item with a machine `code`. Rows saved before
that hold free text in one of three older shapes:

- an error card with `message_data.details`;
- an older error card with a plain `message_data.error` and no `details`;
- a session with a plain `status_data.error`.

This rewrites them into items with code `unknown`. A non-empty string becomes the
`detail` unchanged; anything else (an object, a list, null, an empty string) gets a
fixed text instead, so a stored structure never reaches the user.

The message table is the largest in the database, so both tables are updated in SQL,
without loading rows into Python, one `id` range of BATCH_SIZE rows per statement.
The migration is not atomic: each statement commits on its own, so no statement holds
the table for long. Rerunning is safe: only rows still in an old shape match.

Reverse writes `detail` back as `details` and as a plain `status_data.error`. An error
card that held a plain `error` comes back with `details` instead, the shape the
previous frontend reads. The original value of a non-string error is lost: it comes
back as the fixed text.
"""

from django.db import migrations
from django.db.models import Max, Min

BATCH_SIZE = 5000

# Frozen copy of foundation's UNKNOWN_ERROR_CODE: a migration must keep doing what it
# did when it was written, whatever the live code renames later.
UNKNOWN_ERROR_CODE = "unknown"

# The frontend shows the same text for an error card it still reads in the old shape.
OLDER_FORMAT_DETAIL = "This error was recorded in an older format."

_FORWARD_DETAILS_MESSAGES_SQL = """
UPDATE {table}
SET message_data = (message_data - 'details') || jsonb_build_object(
    'error', jsonb_build_object(
        'code', %(code)s::text,
        'detail', CASE
            WHEN jsonb_typeof(message_data->'details') = 'string'
                AND message_data->>'details' <> ''
            THEN message_data->>'details'
            ELSE %(older_format_detail)s::text
        END,
        'attr', 'null'::jsonb,
        'context', 'null'::jsonb
    )
)
WHERE id BETWEEN %(first_id)s AND %(last_id)s
    AND message_data->>'message_type' = 'error'
    AND message_data ? 'details'
"""

_FORWARD_PLAIN_ERROR_MESSAGES_SQL = """
UPDATE {table}
SET message_data = message_data || jsonb_build_object(
    'error', jsonb_build_object(
        'code', %(code)s::text,
        'detail', CASE
            WHEN jsonb_typeof(message_data->'error') = 'string'
                AND message_data->>'error' <> ''
            THEN message_data->>'error'
            ELSE %(older_format_detail)s::text
        END,
        'attr', 'null'::jsonb,
        'context', 'null'::jsonb
    )
)
WHERE id BETWEEN %(first_id)s AND %(last_id)s
    AND message_data->>'message_type' = 'error'
    AND message_data ? 'error'
    AND jsonb_typeof(message_data->'error') <> 'object'
    AND NOT message_data ? 'details'
"""

_FORWARD_SESSIONS_SQL = """
UPDATE {table}
SET status_data = jsonb_set(
    status_data,
    ARRAY['error'],
    jsonb_build_object(
        'code', %(code)s::text,
        'detail', CASE
            WHEN jsonb_typeof(status_data->'error') = 'string'
                AND status_data->>'error' <> ''
            THEN status_data->>'error'
            ELSE %(older_format_detail)s::text
        END,
        'attr', 'null'::jsonb,
        'context', 'null'::jsonb
    )
)
WHERE id BETWEEN %(first_id)s AND %(last_id)s
    AND status_data ? 'error'
    AND jsonb_typeof(status_data->'error') <> 'object'
"""

# `->>` of a missing `detail` is SQL NULL; `jsonb_build_object` stores it as JSON null.
_REVERSE_MESSAGES_SQL = """
UPDATE {table}
SET message_data = (message_data - 'error')
    || jsonb_build_object('details', message_data->'error'->>'detail')
WHERE id BETWEEN %(first_id)s AND %(last_id)s
    AND message_data->>'message_type' = 'error'
    AND jsonb_typeof(message_data->'error') = 'object'
"""

# `to_jsonb(NULL)` is SQL NULL, and `jsonb_set` with it would null the whole column.
_REVERSE_SESSIONS_SQL = """
UPDATE {table}
SET status_data = jsonb_set(
    status_data,
    ARRAY['error'],
    COALESCE(to_jsonb(status_data->'error'->>'detail'), 'null'::jsonb)
)
WHERE id BETWEEN %(first_id)s AND %(last_id)s
    AND jsonb_typeof(status_data->'error') = 'object'
"""


# The values the forward statements build the item from.
_ITEM_VALUES = {"code": UNKNOWN_ERROR_CODE, "older_format_detail": OLDER_FORMAT_DETAIL}


def _update_in_id_ranges(schema_editor, model, statements: list[str], values: dict) -> None:
    """Run every statement over each `id` range of the model's table, in order."""
    alias = schema_editor.connection.alias
    bounds = model.objects.using(alias).aggregate(first_id=Min("id"), last_id=Max("id"))
    if bounds["first_id"] is None:
        return
    table = schema_editor.quote_name(model._meta.db_table)
    sql_statements = [statement.format(table=table) for statement in statements]
    # Outside an atomic migration the connection autocommits: each statement is its
    # own transaction.
    with schema_editor.connection.cursor() as cursor:
        for first_id in range(bounds["first_id"], bounds["last_id"] + 1, BATCH_SIZE):
            id_range = {"first_id": first_id, "last_id": first_id + BATCH_SIZE - 1}
            for sql in sql_statements:
                cursor.execute(sql, {**values, **id_range})


def errors_to_error_items(apps, schema_editor):
    message_model = apps.get_model("tables", "GraphSessionMessage")
    session_model = apps.get_model("tables", "Session")
    _update_in_id_ranges(
        schema_editor,
        message_model,
        [_FORWARD_DETAILS_MESSAGES_SQL, _FORWARD_PLAIN_ERROR_MESSAGES_SQL],
        _ITEM_VALUES,
    )
    _update_in_id_ranges(schema_editor, session_model, [_FORWARD_SESSIONS_SQL], _ITEM_VALUES)


def error_items_to_errors(apps, schema_editor):
    message_model = apps.get_model("tables", "GraphSessionMessage")
    session_model = apps.get_model("tables", "Session")
    _update_in_id_ranges(schema_editor, message_model, [_REVERSE_MESSAGES_SQL], {})
    _update_in_id_ranges(schema_editor, session_model, [_REVERSE_SESSIONS_SQL], {})


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tables", "0296_merge_20261118_1445"),
    ]

    operations = [
        migrations.RunPython(errors_to_error_items, error_items_to_errors),
    ]
