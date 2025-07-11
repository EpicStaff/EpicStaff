import time
import os
from django.core.management.base import BaseCommand
import psycopg2
from psycopg2 import OperationalError
from loguru import logger


class Command(BaseCommand):
    help = "Wait for Postgres database to be ready before starting the app."

    def handle(self, *args, **options):

        db_user = os.getenv("DB_USER")
        db_password = os.getenv("POSTGRES_PASSWORD")
        db_host = os.getenv("DB_HOST_NAME")
        db_port = os.getenv("DB_PORT")
        db_name = os.getenv("DB_NAME")

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
