from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('tables', '0144_merge_add_meta_fields'),
    ]

    operations = [
        migrations.RunSQL(
            sql=r"""
            -- 0) Create the shared sequence
            CREATE SEQUENCE IF NOT EXISTS tables_global_node_seq;

            DO $$
            DECLARE
              t regclass;
              fk record;
              mapping_table text;
              max_id bigint;
            BEGIN
              -- 1) List of tables
              FOREACH t IN ARRAY ARRAY[
                'tables_crewnode'::regclass,
                'tables_pythonnode'::regclass,
                'tables_fileextractornode'::regclass,
                'tables_audiotranscriptionnode'::regclass,
                'tables_llmnode'::regclass,
                'tables_endnode'::regclass,
                'tables_subgraphnode'::regclass,
                'tables_startnode'::regclass,
                'tables_decisiontablenode'::regclass,
                'tables_webhooktriggernode'::regclass,
                'tables_telegramtriggernode'::regclass
              ]
              LOOP
                -- 2) Lock the table
                EXECUTE format('LOCK TABLE %s IN ACCESS EXCLUSIVE MODE', t);

                -- [MOVED UP] 3) Clean up table structure BEFORE data updates.
                -- This prevents "pending trigger events" errors because no updates have happened yet.
                EXECUTE format('ALTER TABLE %s ALTER COLUMN id DROP IDENTITY IF EXISTS', t);
                EXECUTE format('ALTER TABLE %s ALTER COLUMN id DROP DEFAULT', t);

                -- 4) Create mapping table
                mapping_table := format('tmp_map_%s', replace(t::text, '.', '_'));
                EXECUTE format('DROP TABLE IF EXISTS %I', mapping_table);
                EXECUTE format(
                  'CREATE TEMP TABLE %I (old_id bigint PRIMARY KEY, new_id bigint UNIQUE) ON COMMIT DROP',
                  mapping_table
                );

                -- Fill mapping
                EXECUTE format(
                  'INSERT INTO %I (old_id, new_id)
                   SELECT id, nextval(''tables_global_node_seq'')
                   FROM %s
                   ORDER BY id',
                  mapping_table, t
                );

                -- 5) Update Foreign Keys
                FOR fk IN
                  SELECT
                    con.oid as con_oid,
                    rel_src.oid as src_relid,
                    rel_src.relname as src_table,
                    ns_src.nspname as src_schema,
                    att_src.attname as src_col
                  FROM pg_constraint con
                  JOIN pg_class rel_tgt ON rel_tgt.oid = con.confrelid
                  JOIN pg_namespace ns_tgt ON ns_tgt.oid = rel_tgt.relnamespace
                  JOIN pg_class rel_src ON rel_src.oid = con.conrelid
                  JOIN pg_namespace ns_src ON ns_src.oid = rel_src.relnamespace
                  JOIN pg_attribute att_src
                    ON att_src.attrelid = rel_src.oid
                   AND att_src.attnum = con.conkey[1]
                  WHERE con.contype = 'f'
                    AND con.confrelid = t
                    AND con.confkey = ARRAY[
                      (SELECT attnum FROM pg_attribute WHERE attrelid = t AND attname = 'id' AND NOT attisdropped)
                    ]
                LOOP
                  EXECUTE format('LOCK TABLE %I.%I IN ACCESS EXCLUSIVE MODE', fk.src_schema, fk.src_table);
                  
                  EXECUTE format(
                    'UPDATE %I.%I s
                     SET %I = m.new_id
                     FROM %I m
                     WHERE s.%I = m.old_id',
                    fk.src_schema, fk.src_table,
                    fk.src_col,
                    mapping_table,
                    fk.src_col
                  );
                END LOOP;

                -- 6) Update Primary Key
                EXECUTE format(
                  'UPDATE %s tgt
                   SET id = m.new_id
                   FROM %I m
                   WHERE tgt.id = m.old_id',
                  t, mapping_table
                );

                -- [ADDED] 7) Force execution of pending trigger checks (Foreign Keys)
                -- This clears the queue so we can perform the final ALTER TABLE without error.
                EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';

                -- 8) Set new Default
                EXECUTE format(
                  'ALTER TABLE %s ALTER COLUMN id SET DEFAULT nextval(''tables_global_node_seq'')',
                  t
                );

              END LOOP;

              -- 9) Sync sequence
              EXECUTE 'SELECT GREATEST(
                (SELECT COALESCE(MAX(id), 0) FROM tables_crewnode),
                (SELECT COALESCE(MAX(id), 0) FROM tables_pythonnode),
                (SELECT COALESCE(MAX(id), 0) FROM tables_fileextractornode),
                (SELECT COALESCE(MAX(id), 0) FROM tables_audiotranscriptionnode),
                (SELECT COALESCE(MAX(id), 0) FROM tables_llmnode),
                (SELECT COALESCE(MAX(id), 0) FROM tables_endnode),
                (SELECT COALESCE(MAX(id), 0) FROM tables_subgraphnode),
                (SELECT COALESCE(MAX(id), 0) FROM tables_startnode),
                (SELECT COALESCE(MAX(id), 0) FROM tables_decisiontablenode),
                (SELECT COALESCE(MAX(id), 0) FROM tables_webhooktriggernode),
                (SELECT COALESCE(MAX(id), 0) FROM tables_telegramtriggernode)
              )' INTO max_id;
              IF max_id < 1 THEN
                -- If tables are empty, reset sequence so the NEXT value is 1
                PERFORM setval('tables_global_node_seq', 1, false);
              ELSE
                -- If data exists, set sequence to the max_id
                PERFORM setval('tables_global_node_seq', max_id, true);
              END IF;

            END $$;
            """,
            reverse_sql=r"""
            ALTER TABLE tables_crewnode ALTER COLUMN id DROP DEFAULT;
            ALTER TABLE tables_pythonnode ALTER COLUMN id DROP DEFAULT;
            ALTER TABLE tables_fileextractornode ALTER COLUMN id DROP DEFAULT;
            ALTER TABLE tables_audiotranscriptionnode ALTER COLUMN id DROP DEFAULT;
            ALTER TABLE tables_llmnode ALTER COLUMN id DROP DEFAULT;
            ALTER TABLE tables_endnode ALTER COLUMN id DROP DEFAULT;
            ALTER TABLE tables_subgraphnode ALTER COLUMN id DROP DEFAULT;
            ALTER TABLE tables_startnode ALTER COLUMN id DROP DEFAULT;
            ALTER TABLE tables_decisiontablenode ALTER COLUMN id DROP DEFAULT;
            ALTER TABLE tables_webhooktriggernode ALTER COLUMN id DROP DEFAULT;
            ALTER TABLE tables_telegramtriggernode ALTER COLUMN id DROP DEFAULT;

            DROP SEQUENCE IF EXISTS tables_global_node_seq;
            """
        )
    ]