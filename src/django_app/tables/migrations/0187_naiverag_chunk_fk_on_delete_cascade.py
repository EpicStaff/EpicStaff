# Convert NaiveRag chunk/embedding/preview FKs into the document config to native
# ON DELETE CASCADE. Django emulates cascade in Python (snapshot of child PKs),
# which races the knowledge indexing worker: it inserts new chunks/embeddings in
# its own short transactions while a collection delete is in flight, so the parent
# delete fails the FK check (chunks inserted after the snapshot still reference the
# config). A DB-level cascade removes the subtree atomically with the parent delete
# and serializes against concurrent inserts via the parent row lock, so the late
# insert is either cascaded away or fails harmlessly in the worker (which already
# swallows ForeignKeyViolation). See migration 0127 for the same pattern.

from django.db import migrations


# (child_table, child_column, parent_table, parent_column)
_FK_TARGETS = """
    ('tables_naiveragchunk',        'naive_rag_document_config_id', 'tables_naiveragdocumentconfig', 'naive_rag_document_id'),
    ('tables_naiveragembedding',    'naive_rag_document_config_id', 'tables_naiveragdocumentconfig', 'naive_rag_document_id'),
    ('tables_naiveragembedding',    'chunk_id',                     'tables_naiveragchunk',          'chunk_id'),
    ('tables_naiveragpreviewchunk', 'naive_rag_document_config_id', 'tables_naiveragdocumentconfig', 'naive_rag_document_id')
"""


def _recreate_fks_sql(action_clause: str, suffix: str) -> str:
    """Resolve each existing single-column FK by catalog (its Django-hashed name is
    environment-stable but unknown for some of these), drop it, and recreate with
    `action_clause`. Idempotent: rerun finds the recreated name and replaces it."""
    return f"""
    DO $$
    DECLARE
        rec record;
        con_name text;
    BEGIN
        FOR rec IN
            SELECT * FROM (VALUES
                {_FK_TARGETS}
            ) AS t(child_table, child_col, parent_table, parent_col)
        LOOP
            SELECT con.conname INTO con_name
            FROM pg_constraint con
            JOIN pg_attribute att
              ON att.attrelid = con.conrelid
             AND att.attnum = ANY (con.conkey)
            WHERE con.conrelid = rec.child_table::regclass
              AND con.contype = 'f'
              AND att.attname = rec.child_col
              AND array_length(con.conkey, 1) = 1
            LIMIT 1;

            IF con_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I',
                               rec.child_table, con_name);
            END IF;

            EXECUTE format(
                'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (%I) '
                'REFERENCES %I (%I) {action_clause}',
                rec.child_table,
                left(rec.child_table || '_' || rec.child_col || '_{suffix}', 63),
                rec.child_col,
                rec.parent_table,
                rec.parent_col
            );
        END LOOP;
    END $$;
    """


class Migration(migrations.Migration):

    dependencies = [
        ('tables', '0186_naiveragdocumentconfig_error_code_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            sql=_recreate_fks_sql("ON DELETE CASCADE", "fk_cascade"),
            # Restore Django's default FK (NO ACTION) with its deferrable convention.
            reverse_sql=_recreate_fks_sql("DEFERRABLE INITIALLY DEFERRED", "fk"),
        )
    ]
