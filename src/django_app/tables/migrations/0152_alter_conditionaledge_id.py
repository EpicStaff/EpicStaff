import tables.models.base_models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0151_merge_est_2006"),
    ]

    operations = [
        migrations.RunSQL(
            sql=r"""
            DO $$
            DECLARE
              t regclass := 'tables_conditionaledge'::regclass;
              fk record;
              mapping_table text;
              max_id bigint;
            BEGIN
              -- 1) Lock the table
              EXECUTE format('LOCK TABLE %s IN ACCESS EXCLUSIVE MODE', t);

              -- 2) Clean up table structure BEFORE data updates.
              EXECUTE format('ALTER TABLE %s ALTER COLUMN id DROP IDENTITY IF EXISTS', t);
              EXECUTE format('ALTER TABLE %s ALTER COLUMN id DROP DEFAULT', t);

              -- 3) Create mapping table
              mapping_table := 'tmp_map_tables_conditionaledge';
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

              -- 4) Update Foreign Keys referencing this table
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

              -- 5) Update Primary Key
              EXECUTE format(
                'UPDATE %s tgt
                 SET id = m.new_id
                 FROM %I m
                 WHERE tgt.id = m.old_id',
                t, mapping_table
              );

              -- 6) Force execution of pending trigger checks
              EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';

              -- 7) Set new Default
              EXECUTE format(
                'ALTER TABLE %s ALTER COLUMN id SET DEFAULT nextval(''tables_global_node_seq'')',
                t
              );

              -- 8) Sync sequence
              SELECT COALESCE(MAX(id), 0) INTO max_id FROM tables_conditionaledge;
              IF max_id >= 1 THEN
                PERFORM setval('tables_global_node_seq', max_id, true);
              END IF;

            END $$;
            """,
            reverse_sql=r"""
            ALTER TABLE tables_conditionaledge ALTER COLUMN id DROP DEFAULT;
            """,
        ),
        migrations.AlterField(
            model_name="conditionaledge",
            name="id",
            field=models.BigIntegerField(
                db_default=tables.models.base_models.NextVal(
                    models.Value("tables_global_node_seq")
                ),
                editable=False,
                primary_key=True,
                serialize=False,
            ),
        ),
    ]
