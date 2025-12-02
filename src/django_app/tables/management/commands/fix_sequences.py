from django.core.management.base import BaseCommand
from django.apps import apps
from django.db import connection
from loguru import logger

class Command(BaseCommand):
    help = "fix db sequences for all project models"

    def handle(self, *args, **options):
        fixed_count = 0
        with connection.cursor() as cursor:

            for model in apps.get_models():
                meta = model._meta

                if not meta.pk or meta.pk.attname != "id":
                    continue

                if meta.pk.get_internal_type() not in ("AutoField", "BigAutoField", "SmallAutoField"):
                    continue

                try:
                    cursor.execute(f"""
                        SELECT setval(
                            pg_get_serial_sequence('"{meta.db_table}"', 'id'),
                            GREATEST((SELECT COALESCE(MAX(id), 0) FROM "{meta.db_table}"), 1)
                        );
                    """)
                    fixed_count += 1
                except Exception:
                    continue
                
        if fixed_count:
            logger.success(f"Fixed sequences for {fixed_count} tables")
        else:
            logger.info("No sequences fixed")
