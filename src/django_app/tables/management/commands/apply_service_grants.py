"""Grant the manager, knowledge and realtime roles their table privileges.

entrypoint.sh runs this right after ``migrate``. Postgres GRANT and REVOKE rewrite a
table's catalog row without locking the table, so a grant running while a migration
alters that table fails with "tuple concurrently updated". Run here, nothing else changes
the schema at the same time. The command is idempotent and applied on every start, so an
existing database converges on the matrix in tables/service_db_grants.py whenever it
changes. crewdb creates the roles themselves before it reports healthy.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django_app.settings import env
from loguru import logger
from tables.service_db_grants import SERVICE_ROLE_GRANTS, grant_statements


class Command(BaseCommand):
    help = (
        "Grant the manager, knowledge and realtime database roles the privileges in "
        "tables/service_db_grants.py. Run after migrate."
    )

    def handle(self, *args, **options):
        role_names = {
            service_grants.service: self._role_name(service_grants.role_variable)
            for service_grants in SERVICE_ROLE_GRANTS
        }

        # One transaction: a service connected meanwhile never sees a table between its
        # REVOKE and its GRANT, and a failure leaves the previous grants untouched.
        with transaction.atomic(), connection.cursor() as cursor:
            self._require_roles_exist(cursor, set(role_names.values()))
            for service_grants in SERVICE_ROLE_GRANTS:
                role = role_names[service_grants.service]
                for statement in grant_statements(service_grants, role):
                    cursor.execute(statement)
                logger.info(
                    "Granted {service} role {role} privileges on {tables} tables and "
                    "{sequences} sequences",
                    service=service_grants.service,
                    role=role,
                    tables=len(service_grants.tables),
                    sequences=len(service_grants.sequences),
                )

        logger.success("Service role grants applied")

    @staticmethod
    def _role_name(role_variable: str) -> str:
        role = env.str(role_variable, "")
        if not role:
            raise CommandError(
                f"{role_variable} is not set: django_app needs it to grant that role its "
                "table privileges."
            )
        return role

    @staticmethod
    def _require_roles_exist(cursor, roles: set[str]) -> None:
        cursor.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", [list(roles)])
        missing = roles - {row[0] for row in cursor.fetchall()}
        if missing:
            raise CommandError(
                f"Database role(s) {', '.join(sorted(missing))} do not exist. crewdb creates "
                "them at startup; check the crewdb log for a setup error."
            )
