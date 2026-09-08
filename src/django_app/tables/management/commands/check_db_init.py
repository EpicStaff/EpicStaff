import time
import os
from django.core.management.base import BaseCommand
import psycopg2
from psycopg2 import OperationalError
from loguru import logger

from django_app.settings import env


class Command(BaseCommand):
    help = "Wait for Postgres database to be ready before starting the app."

    def handle(self, *args, **options):
        db_user = env.str("DJANGO_DB_USER")
        db_password = env.str("DJANGO_DB_PASSWORD")
        db_host = env.str("DB_HOST")
        db_port = env.int("DB_PORT")
        db_name = env.str("DB_NAME")

        for attempt in range(1, 151):
            try:
                conn = psycopg2.connect(
                    host=db_host,
                    port=db_port,
                    user=db_user,
                    password=db_password,
                    dbname=db_name,
                )
                conn.close()
                logger.success("Postgres is ready!")
                return  # success
            except OperationalError:
                logger.warning(f"Trying again to connect to Postgres: {attempt}/150")
                time.sleep(2)

        logger.error(
            "Failed to connect to Postgres after 150 attempts (approx. 300 seconds). Exiting."
        )
        raise RuntimeError("Postgres is not ready after 150 attempts")
